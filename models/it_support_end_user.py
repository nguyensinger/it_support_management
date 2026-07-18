# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ItSupportEndUser(models.Model):
    _name = 'it.support.end.user'
    _description = 'IT Support End User'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Full Name', required=True, tracking=True)
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    department = fields.Char(string='Department')
    job_title = fields.Char(string='Job Title')
    customer_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain="[('is_company', '=', True)]", tracking=True,
        ondelete='cascade',
    )
    device_ids = fields.One2many(
        'it.customer.device', 'user_id', string='Devices Used'
    )
    device_count = fields.Integer(compute='_compute_device_count', string='Device Count')
    ticket_ids = fields.One2many(
        'it.support.ticket', 'end_user_id', string='Tickets'
    )
    active = fields.Boolean(default=True)

    @api.depends('device_ids')
    def _compute_device_count(self):
        for rec in self:
            rec.device_count = len(rec.device_ids)
