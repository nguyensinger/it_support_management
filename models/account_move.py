# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    project_id = fields.Many2one(
        'it.project.project', string='IT Project',
        help='Tag this vendor bill as an input cost for a specific IT project (materials, '
             'equipment, subcontracted labour...). Leave empty for a general company expense.',
    )
    expense_category_id = fields.Many2one(
        'it.expense.category', string='Expense Category',
        help='Tag this vendor bill as a general recurring company expense (rent, utilities, '
             'software subscriptions...) not tied to a specific customer project.',
    )
