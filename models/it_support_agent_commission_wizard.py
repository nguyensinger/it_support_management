# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ItSupportAgentCommissionWizard(models.TransientModel):
    _name = 'it.support.agent.commission.wizard'
    _description = 'Set IT Support Agent Commission Rate'

    agent_id = fields.Many2one(
        'res.users', string='Agent', required=True,
        domain=[('is_it_support_staff', '=', True)],
    )
    commission_rate = fields.Float(string='Commission Rate (%)', required=True, default=60.0)

    @api.onchange('agent_id')
    def _onchange_agent_id(self):
        if self.agent_id:
            self.commission_rate = self.agent_id.it_support_commission_rate

    def action_apply(self):
        """Writes to res.users via sudo() rather than granting IT Support Manager
        broader write access on res.users (which base Odoo restricts to
        group_erp_manager/Settings) - this keeps the change limited to exactly
        the one field this wizard exposes.
        """
        self.ensure_one()
        self.agent_id.sudo().write({'it_support_commission_rate': self.commission_rate})
