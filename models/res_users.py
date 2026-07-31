# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    it_support_commission_rate = fields.Float(
        string='IT Support Commission Rate (%)', default=60.0,
        help='Percentage of the billed session revenue this agent earns as commission. '
             'Snapshotted onto each monthly payroll record when it is generated, so '
             'changing this later does not retroactively affect past payroll.',
    )
    is_it_support_staff = fields.Boolean(
        compute='_compute_is_it_support_staff', store=True,
        string='Is IT Support Staff',
    )

    @api.depends('group_ids')
    def _compute_is_it_support_staff(self):
        agent_group = self.env.ref('it_support_management.group_it_support_agent')
        manager_group = self.env.ref('it_support_management.group_it_support_manager')
        staff_groups = agent_group | manager_group
        for user in self:
            user.is_it_support_staff = bool(user.group_ids & staff_groups)
