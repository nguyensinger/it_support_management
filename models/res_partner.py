# -*- coding: utf-8 -*-
from odoo import fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    device_ids = fields.One2many('it.customer.device', 'customer_id', string='IT Devices')
    end_user_ids = fields.One2many('it.support.end.user', 'customer_id', string='IT Users')
    it_ticket_ids = fields.One2many('it.support.ticket', 'customer_id', string='IT Support Tickets')
    device_count = fields.Integer(compute='_compute_it_counts')
    it_ticket_count = fields.Integer(compute='_compute_it_counts')
    preferred_agent_id = fields.Many2one(
        'res.users', string='Preferred IT Agent',
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
        help='The agent who usually handles this customer. New tickets are assigned to '
             'this agent automatically IF they are on duty at the time the ticket is '
             'created; otherwise the ticket goes to whoever is on duty.',
    )
    reseller_id = fields.Many2one(
        'res.partner', string='Billing Partner (Reseller)',
        domain="[('is_company', '=', True), ('id', '!=', id)]",
        help='If this customer was referred to us by a subcontract partner, set that '
             'partner here. IT support is still delivered directly to this customer, but '
             'pricing uses that partner\'s rates (see Support Types & Pricing) and the '
             'monthly invoice for this customer\'s work is billed to the partner instead '
             'of to the customer directly.',
    )

    def _compute_it_counts(self):
        for rec in self:
            rec.device_count = len(rec.device_ids)
            rec.it_ticket_count = len(rec.it_ticket_ids)

    def action_view_it_devices(self):
        self.ensure_one()
        return {
            'name': _('IT Devices'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.customer.device',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }

    def action_view_it_tickets(self):
        self.ensure_one()
        return {
            'name': _('IT Support Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.ticket',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }
