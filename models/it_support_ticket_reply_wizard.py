# -*- coding: utf-8 -*-
from odoo import fields, models


class ItSupportTicketReplyWizard(models.TransientModel):
    _name = 'it.support.ticket.reply.wizard'
    _description = 'Send Reply to Customer'

    ticket_id = fields.Many2one('it.support.ticket', string='Ticket', required=True)
    body = fields.Text(string='Reply', required=True)

    def action_send(self):
        self.ensure_one()
        self.ticket_id.action_send_reply(self.body)
        return {'type': 'ir.actions.act_window_close'}
