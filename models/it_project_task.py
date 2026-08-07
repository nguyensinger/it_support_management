# -*- coding: utf-8 -*-
from odoo import fields, models


class ItProjectTask(models.Model):
    _name = 'it.project.task'
    _description = 'IT Project Task'
    _order = 'sequence, deadline, id'

    project_id = fields.Many2one('it.project.project', string='Project', required=True, ondelete='cascade')
    customer_id = fields.Many2one(related='project_id.customer_id', string='Customer', store=True, readonly=True)
    sequence = fields.Integer(default=10)

    name = fields.Char(string='Task', required=True)
    assigned_to = fields.Many2one(
        'res.users', string='Assigned To',
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
    )
    deadline = fields.Date(string='Deadline')
    note = fields.Text(string='Notes')

    state = fields.Selection([
        ('to_do', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='to_do')

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'to_do'})
