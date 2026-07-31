# -*- coding: utf-8 -*-
from odoo import fields, models, _


class ItSupportAgentPayrollGenerateWizard(models.TransientModel):
    _name = 'it.support.agent.payroll.generate.wizard'
    _description = 'Generate Agent Monthly Payroll Wizard'

    month = fields.Selection(
        [(str(i), str(i)) for i in range(1, 13)], string='Month', required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    agent_ids = fields.Many2many(
        'res.users', string='Agents (leave empty for all)',
        domain=[('is_it_support_staff', '=', True)],
    )

    def action_generate(self):
        self.ensure_one()
        Payroll = self.env['it.support.agent.payroll']
        agent_ids = self.agent_ids.ids or None
        payrolls = Payroll.generate_for_period(int(self.month), self.year, agent_ids=agent_ids)

        if not payrolls:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No payroll generated'),
                    'message': _('No closed sessions on invoiced tickets were found for this period.'),
                    'type': 'warning',
                },
            }

        return {
            'name': _('Generated Payroll'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.agent.payroll',
            'view_mode': 'list,form',
            'domain': [('id', 'in', payrolls.ids)],
        }
