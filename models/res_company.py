# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    etransfer_email = fields.Char(
        string='e-Transfer Payment Email',
        help='Shown on IT Support invoices under Payment Methods as the address customers '
             'should send Interac e-Transfer payments to.',
    )
