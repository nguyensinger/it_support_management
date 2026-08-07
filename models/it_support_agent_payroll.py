# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class ItSupportAgentPayroll(models.Model):
    _name = 'it.support.agent.payroll'
    _description = 'IT Support Agent Monthly Payroll'
    _order = 'year desc, month desc, agent_id'
    _rec_name = 'display_name'

    agent_id = fields.Many2one('res.users', string='Agent', required=True)
    month = fields.Selection([(str(i), str(i)) for i in range(1, 13)], string='Month', required=True)
    year = fields.Integer(string='Year', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    commission_rate = fields.Float(
        string='Commission Rate (%)', required=True,
        help="Snapshot of the agent's commission rate at the time this payroll was "
             "generated. Editable while still Draft; changing the agent's rate on their "
             "user profile afterwards does not retroactively affect this record.",
    )

    session_ids = fields.One2many(
        'it.support.session', 'payroll_id', string='Sessions (solo)',
        help='Sessions with no declared participants (the default: just this agent, at 100%).',
    )
    participant_line_ids = fields.One2many(
        'it.support.session.participant', 'payroll_id', string='Session Participations',
        help='This agent\'s declared share of sessions where 2+ technicians worked together.',
    )
    session_count = fields.Integer(compute='_compute_totals', string='Session Count')
    total_hours = fields.Float(compute='_compute_totals', string='Billable Hours')
    total_revenue = fields.Monetary(compute='_compute_totals', string='Session Revenue', store=True)
    commission_amount = fields.Monetary(compute='_compute_totals', string='Commission Amount', store=True)

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
    ], string='Status', default='draft', tracking=True)
    paid_date = fields.Date(string='Paid On', readonly=True, copy=False)

    _unique_agent_month_year = models.Constraint(
        'unique(agent_id, month, year)',
        'A payroll record for this agent in this month/year already exists!',
    )

    @api.depends('agent_id', 'month', 'year')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.agent_id.name} - {rec.month}/{rec.year}" if rec.agent_id else ''

    @api.depends('session_ids.duration', 'session_ids.support_mode',
                 'session_ids.support_mode_type_id.price_per_hour',
                 'session_ids.support_mode_type_id.first_block_minutes',
                 'session_ids.support_mode_type_id.block_minutes',
                 'session_ids.support_mode_type_id.min_charge_blocks',
                 'participant_line_ids.percentage',
                 'participant_line_ids.session_id.duration',
                 'participant_line_ids.session_id.participant_count',
                 'participant_line_ids.session_id.support_mode_type_id.price_per_hour',
                 'participant_line_ids.session_id.support_mode_type_id.first_block_minutes',
                 'participant_line_ids.session_id.support_mode_type_id.block_minutes',
                 'participant_line_ids.session_id.support_mode_type_id.min_charge_blocks',
                 'commission_rate')
    def _compute_totals(self):
        for rec in self:
            hours = 0.0
            revenue = 0.0
            # Solo sessions (no declared participants) - this agent gets the full session
            # revenue, exactly as before this feature existed.
            for session in rec.session_ids:
                support_type = session.support_mode_type_id or session.ticket_id.support_type_id
                if not support_type:
                    continue
                hours += support_type.compute_billable_hours(session.duration)
                revenue += support_type.compute_amount(session.duration)
            # Multi-participant sessions - this agent only gets their declared share of the
            # (participant-count-multiplied) session revenue.
            for line in rec.participant_line_ids:
                session = line.session_id
                support_type = session.support_mode_type_id or session.ticket_id.support_type_id
                if not support_type:
                    continue
                share = line.percentage / 100.0
                hours += support_type.compute_billable_hours(session.duration) * session.participant_count * share
                revenue += support_type.compute_amount(session.duration) * session.participant_count * share
            rec.session_count = len(rec.session_ids) + len(rec.participant_line_ids)
            rec.total_hours = hours
            rec.total_revenue = revenue
            rec.commission_amount = revenue * (rec.commission_rate / 100.0)

    @api.model
    def generate_for_period(self, month, year, agent_ids=None):
        """Scan closed sessions belonging to INVOICED tickets for the given month/year
        (by session end_time), group by agent, and create/refresh the corresponding
        payroll record. Only invoiced tickets count, so commission is only paid out on
        revenue actually billed to the customer.

        Two kinds of contributions get claimed, per agent:
        - "Solo" sessions with no declared participants (the default: just the agent_id
          on the session, at 100%) - claimed via session.payroll_id, exactly as before
          multi-participant sessions existed.
        - Participant lines on sessions where 2+ technicians were declared - each
          it.support.session.participant row is claimed individually via its own
          payroll_id, crediting only that agent's declared percentage share.

        Either way, something already claimed (payroll_id set) is never picked up again,
        so re-running this for the same period only adds newly-eligible contributions
        (e.g. a ticket invoiced late). If the existing payroll record for an agent/period
        is no longer Draft (already Confirmed/Paid), newly-eligible contributions are left
        unclaimed rather than silently changing an already-settled payroll amount - the
        manager can review and add them manually.
        """
        Session = self.env['it.support.session']
        Participant = self.env['it.support.session.participant']
        date_from = fields.Date.to_date(f'{year}-{int(month):02d}-01')
        date_to = date_from + relativedelta(months=1)

        session_domain = [
            ('state', '=', 'closed'),
            ('end_time', '>=', date_from),
            ('end_time', '<', date_to),
            ('payroll_id', '=', False),
            ('participant_ids', '=', False),
            ('ticket_id.is_invoiced', '=', True),
        ]
        if agent_ids:
            session_domain.append(('agent_id', 'in', agent_ids))
        solo_sessions = Session.search(session_domain)

        participant_domain = [
            ('payroll_id', '=', False),
            ('session_id.state', '=', 'closed'),
            ('session_id.end_time', '>=', date_from),
            ('session_id.end_time', '<', date_to),
            ('session_id.ticket_id.is_invoiced', '=', True),
        ]
        if agent_ids:
            participant_domain.append(('agent_id', 'in', agent_ids))
        participant_lines = Participant.search(participant_domain)

        by_agent_sessions = {}
        for session in solo_sessions:
            by_agent_sessions.setdefault(session.agent_id.id, []).append(session.id)

        by_agent_lines = {}
        for line in participant_lines:
            by_agent_lines.setdefault(line.agent_id.id, []).append(line.id)

        payrolls = self.env['it.support.agent.payroll']
        for agent_id in set(by_agent_sessions) | set(by_agent_lines):
            payroll = self.search([
                ('agent_id', '=', agent_id),
                ('month', '=', str(int(month))),
                ('year', '=', year),
            ], limit=1)
            if not payroll:
                agent = self.env['res.users'].browse(agent_id)
                payroll = self.create({
                    'agent_id': agent_id,
                    'month': str(int(month)),
                    'year': year,
                    'commission_rate': agent.it_support_commission_rate,
                })
            elif payroll.state != 'draft':
                _logger.warning(
                    'Skipping newly-invoiced contribution(s) for agent %s, %s/%s: existing '
                    'payroll record is already %s. Add them to a new/manual record instead.',
                    payroll.agent_id.name, month, year, payroll.state,
                )
                continue
            session_ids = by_agent_sessions.get(agent_id)
            if session_ids:
                Session.browse(session_ids).write({'payroll_id': payroll.id})
            line_ids = by_agent_lines.get(agent_id)
            if line_ids:
                Participant.browse(line_ids).write({'payroll_id': payroll.id})
            payrolls |= payroll
        return payrolls

    @api.model
    def _cron_generate_previous_month_payroll(self):
        """Wrapper called from ir.cron - see _cron_generate_previous_month_summary in
        it_support_monthly_summary.py for why this indirection is needed (safe_eval
        sandbox on ir.cron.code forbids imports).
        """
        today = fields.Date.context_today(self)
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month != 1 else today.year - 1
        self.generate_for_period(prev_month, prev_year)

    def action_open_generate_wizard(self):
        return {
            'name': _('Generate Monthly Payroll'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.agent.payroll.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        for rec in self:
            if not rec.session_ids:
                raise UserError(_('There are no sessions in this payroll record.'))
            rec.state = 'confirmed'

    def action_mark_paid(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed payroll records can be marked as paid.'))
            rec.write({'state': 'paid', 'paid_date': fields.Date.context_today(self)})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('A paid payroll record cannot be reset to draft.'))
            rec.state = 'draft'
