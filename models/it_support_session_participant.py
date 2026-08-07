# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ItSupportSessionParticipant(models.Model):
    _name = 'it.support.session.participant'
    _description = 'IT Support Session Participant (multi-tech commission split)'

    session_id = fields.Many2one('it.support.session', string='Session', required=True, ondelete='cascade')
    ticket_id = fields.Many2one(related='session_id.ticket_id', string='Ticket', store=True, readonly=True)
    agent_id = fields.Many2one(
        'res.users', string='Agent', required=True,
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
    )
    percentage = fields.Float(
        string='Share (%)', required=True, default=100.0,
        help='This agent\'s share of the session revenue used for commission calculation. '
             'All participants\' shares on the same session must add up to 100%.',
    )

    payroll_id = fields.Many2one(
        'it.support.agent.payroll', string='Payroll', readonly=True, copy=False,
        help='Set once this participation has been included in a generated monthly '
             'payroll record for this agent - prevents it from being paid out twice.',
    )

    _percentage_range = models.Constraint(
        'CHECK(percentage > 0 AND percentage <= 100)',
        'The share percentage must be greater than 0 and no more than 100.',
    )

    @api.constrains('percentage', 'session_id')
    def _check_session_percentages_sum(self):
        # Also enforced on it.support.session._check_participant_percentages (fires when
        # the session's own participant_ids field is written, e.g. via the embedded list
        # on the session form) - duplicated here because @api.constrains on the "one" side
        # of a One2many does NOT reliably fire when a child is created/written directly
        # from this model (e.g. Participant.create({'session_id': ...})), only when the
        # parent's own write() touches participant_ids.
        sessions = self.mapped('session_id')
        for session in sessions:
            if not session.participant_ids:
                continue
            total = sum(session.participant_ids.mapped('percentage'))
            if abs(total - 100.0) > 0.01:
                raise UserError(_(
                    'Declared participant shares for a session must add up to 100%% '
                    '(currently %.2f%%).'
                ) % total)

    def unlink(self):
        for rec in self:
            if rec.payroll_id and rec.payroll_id.state != 'draft':
                raise UserError(_(
                    'Cannot remove this participant: it has already been included in a '
                    '%s payroll record for %s.'
                ) % (rec.payroll_id.state, rec.agent_id.name))
        return super().unlink()
