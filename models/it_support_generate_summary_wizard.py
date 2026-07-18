# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ItSupportGenerateSummaryWizard(models.TransientModel):
    _name = 'it.support.generate.summary.wizard'
    _description = 'Generate Monthly Summary Wizard'

    month = fields.Selection(
        [(str(i), str(i)) for i in range(1, 13)], string='Month', required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    customer_ids = fields.Many2many(
        'res.partner', string='Customers (leave empty for all)',
        domain="[('is_company', '=', True)]",
    )

    def action_generate(self):
        self.ensure_one()
        Summary = self.env['it.support.monthly.summary']
        customer_ids = self.customer_ids.ids or None
        summaries = Summary.generate_for_period(int(self.month), self.year, customer_ids=customer_ids)

        if not summaries:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No summary generated'),
                    'message': _('No completed tickets with a closed date in this period were found.'),
                    'type': 'warning',
                },
            }

        return {
            'name': _('Generated Summaries'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.monthly.summary',
            'view_mode': 'list,form',
            'domain': [('id', 'in', summaries.ids)],
        }
