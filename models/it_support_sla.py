# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from datetime import timedelta


class ItSupportSla(models.Model):
    _name = 'it.support.sla'
    _description = 'IT Support SLA Policy'
    _order = 'priority desc'

    name = fields.Char(string='SLA Name', required=True)
    active = fields.Boolean(default=True)

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority', required=True)

    # Response time targets (in hours)
    response_time_hours = fields.Float(
        string='First Response Time (hours)', required=True,
        help='Maximum time allowed for agent to send first response after ticket creation.',
    )
    resolution_time_hours = fields.Float(
        string='Resolution Time (hours)', required=True,
        help='Maximum time allowed to resolve (close) the ticket after creation.',
    )

    description = fields.Text(string='Description')

    def get_sla_for_priority(self, priority):
        """Return the SLA policy for a given priority string."""
        return self.search([('priority', '=', priority), ('active', '=', True)], limit=1)
