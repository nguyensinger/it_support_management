# -*- coding: utf-8 -*-
from odoo import fields, models


class ItExpenseCategory(models.Model):
    _name = 'it.expense.category'
    _description = 'General Company Expense Category'
    _order = 'name'

    name = fields.Char(string='Category', required=True)
    active = fields.Boolean(default=True)
