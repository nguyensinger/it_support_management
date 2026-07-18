# -*- coding: utf-8 -*-
from odoo import fields, models


class ItSupportSessionEndWizard(models.TransientModel):
    _name = 'it.support.session.end.wizard'
    _description = 'End Working Session'

    ticket_id = fields.Many2one('it.support.ticket', string='Ticket', required=True)
    note = fields.Text(string='Work Performed', required=True)
    resolution_status = fields.Selection([
        ('resolved', 'Resolved'),
        ('partially_resolved', 'Partially Resolved'),
        ('not_resolved', 'Not Resolved'),
        ('escalated', 'Escalated'),
    ], string='Resolution Status', required=True)

    def action_confirm(self):
        self.ensure_one()
        # Forwards straight into the same it.support.ticket.action_end_session used
        # by the mobile app's End button - note is also auto-sent to the customer
        # as a reply from there (see action_send_reply).
        self.ticket_id.action_end_session(note=self.note, resolution_status=self.resolution_status)
        return {'type': 'ir.actions.act_window_close'}
