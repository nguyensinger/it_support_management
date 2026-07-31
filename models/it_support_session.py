# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ItSupportSession(models.Model):
    _name = 'it.support.session'
    _description = 'IT Support Working Session (Start/End)'
    _order = 'start_time desc'

    ticket_id = fields.Many2one(
        'it.support.ticket', string='Ticket', required=True, ondelete='cascade',
    )
    customer_id = fields.Many2one(
        related='ticket_id.customer_id', string='Customer', store=True, readonly=True,
    )
    agent_id = fields.Many2one('res.users', string='IT Support Agent', required=True, default=lambda self: self.env.user)
    payroll_id = fields.Many2one(
        'it.support.agent.payroll', string='Payroll', readonly=True, copy=False,
        help='Set once this session has been included in a generated monthly payroll '
             'record for the agent - prevents the same session from being paid out twice.',
    )

    start_time = fields.Datetime(string='Start', required=True, default=fields.Datetime.now)
    end_time = fields.Datetime(string='End')
    duration = fields.Float(
        string='Duration (hours)', compute='_compute_duration', store=True,
    )

    support_mode = fields.Selection([
        ('onsite', 'Onsite'),
        ('online', 'Online'),
    ], string='Actual Mode', required=True, default='online')
    support_mode_type_id = fields.Many2one(
        'it.support.type', string='Applied Pricing', compute='_compute_support_mode_type', store=True,
        help='Pricing entry matching this session\'s actual support mode (used for billing).',
    )

    note = fields.Text(string='Work Notes')
    resolution_status = fields.Selection([
        ('resolved', 'Resolved'),
        ('partially_resolved', 'Partially Resolved'),
        ('not_resolved', 'Not Resolved'),
        ('escalated', 'Escalated'),
    ], string='Resolution Status')
    state = fields.Selection([
        ('running', 'Running'),
        ('closed', 'Closed'),
    ], string='Status', default='running')

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            if rec.start_time and rec.end_time:
                delta = rec.end_time - rec.start_time
                rec.duration = delta.total_seconds() / 3600.0
            else:
                rec.duration = 0.0

    @api.depends('support_mode', 'customer_id.company_type')
    def _compute_support_mode_type(self):
        SupportType = self.env['it.support.type']
        for rec in self:
            rec.support_mode_type_id = SupportType.find_for(rec.support_mode, rec.customer_id.company_type)

    def action_end_session(self, note=None, resolution_status=None):
        """Explicit 'End Session' action - REQUIRES note and resolution_status.
        This is the path used when the agent deliberately ends their session
        (mobile app End button -> it.support.ticket.action_end_session ->
        here). Both fields are mandatory here.
        """
        for rec in self:
            if rec.state != 'running':
                continue
            if not note or not note.strip():
                raise UserError(_('Please describe the work performed before ending the session.'))
            if not resolution_status:
                raise UserError(_('Please select the resolution status before ending the session.'))
            rec.write({
                'end_time': fields.Datetime.now(),
                'state': 'closed',
                'note': note,
                'resolution_status': resolution_status,
            })
        return True

    def _auto_close_session(self):
        """Internal, system-triggered close - used when a ticket is paused,
        marked done, or cancelled while it still has a running session, WITHOUT
        the agent having explicitly used 'End Session' first (see
        it.support.ticket.action_pause/action_done/action_cancel). Unlike
        action_end_session, this does NOT require note/resolution_status - the
        session is simply closed as-is, since there was no dedicated
        end-of-work step. The agent can still fill in the work note and
        resolution status afterwards by editing the session record directly
        (the Working Sessions list is editable).
        """
        for rec in self:
            if rec.state != 'running':
                continue
            rec.with_context(skip_resolution_check=True).write({
                'end_time': fields.Datetime.now(),
                'state': 'closed',
            })
        return True

    @api.constrains('start_time', 'end_time')
    def _check_time_order(self):
        for rec in self:
            if rec.end_time and rec.start_time and rec.end_time < rec.start_time:
                raise UserError(_('The end time cannot be earlier than the start time.'))

    @api.constrains('state', 'note', 'resolution_status')
    def _check_closed_requires_note_and_resolution(self):
        """Safety net for the explicit End Session path: a session closed via
        action_end_session (or any direct write outside of _auto_close_session)
        can never end up 'closed' without a work note and a resolution status.
        _auto_close_session deliberately bypasses this via context, since it
        represents a different business event (ticket paused/cancelled/done by
        the system, not an explicit End Session by the agent).
        """
        for rec in self:
            if self.env.context.get('skip_resolution_check'):
                continue
            if rec.state == 'closed' and (not rec.note or not rec.note.strip() or not rec.resolution_status):
                raise UserError(_(
                    'A session cannot be marked Closed without a work note and a resolution status.'
                ))
