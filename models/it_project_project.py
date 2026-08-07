# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ItProjectProject(models.Model):
    _name = 'it.project.project'
    _description = 'IT Project (Network / Camera / Custom Software)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Project No.', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('it.project.project') or 'New',
    )

    customer_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    project_type = fields.Selection([
        ('network', 'Network Installation'),
        ('camera', 'Camera System'),
        ('software', 'Custom Software'),
        ('other', 'Other'),
    ], string='Project Type', required=True, default='network', tracking=True)
    description = fields.Text(string='Description')
    manager_id = fields.Many2one(
        'res.users', string='Project Lead',
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
    )

    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date (Planned)')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('invoiced', 'Invoiced'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    quoted_amount = fields.Monetary(
        string='Quoted Amount', currency_field='currency_id',
        help='The total agreed price for this project, quoted to the customer.',
    )
    deposit_amount = fields.Monetary(
        string='Deposit / Advance Payment', currency_field='currency_id',
        help='Optional deposit collected before or during the project. Leave at 0 if no deposit is required.',
    )
    balance_due = fields.Monetary(
        string='Balance Due on Completion', compute='_compute_balance_due', store=True,
        currency_field='currency_id',
    )

    task_ids = fields.One2many('it.project.task', 'project_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_stats', string='Task Count')
    open_task_count = fields.Integer(compute='_compute_task_stats', string='Open Tasks')

    cost_bill_ids = fields.One2many(
        'account.move', 'project_id', string='Cost Bills (Vendor Bills)',
        domain=[('move_type', 'in', ('in_invoice', 'in_refund'))],
    )
    total_cost = fields.Monetary(
        string='Total Input Cost', compute='_compute_total_cost', store=True,
        currency_field='currency_id',
        help='Sum of vendor bills (materials, equipment, subcontracted labour...) tagged to this project.',
    )
    estimated_profit = fields.Monetary(
        string='Estimated Profit', compute='_compute_total_cost', store=True,
        currency_field='currency_id',
        help='Quoted Amount minus Total Input Cost.',
    )

    deposit_invoice_id = fields.Many2one('account.move', string='Deposit Invoice', readonly=True, copy=False)
    final_invoice_id = fields.Many2one('account.move', string='Final Invoice', readonly=True, copy=False)

    @api.depends('quoted_amount', 'deposit_amount')
    def _compute_balance_due(self):
        for rec in self:
            rec.balance_due = rec.quoted_amount - rec.deposit_amount

    @api.depends('task_ids.state')
    def _compute_task_stats(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)
            rec.open_task_count = len(rec.task_ids.filtered(lambda t: t.state not in ('done', 'cancelled')))

    @api.depends('cost_bill_ids.amount_total', 'cost_bill_ids.state', 'cost_bill_ids.move_type', 'quoted_amount')
    def _compute_total_cost(self):
        for rec in self:
            bills = rec.cost_bill_ids.filtered(lambda b: b.state == 'posted')
            cost = sum(bills.filtered(lambda b: b.move_type == 'in_invoice').mapped('amount_total'))
            cost -= sum(bills.filtered(lambda b: b.move_type == 'in_refund').mapped('amount_total'))
            rec.total_cost = cost
            rec.estimated_profit = rec.quoted_amount - cost

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def _get_gst_tax(self):
        # Same 5% CA GST lookup used by monthly summary invoicing - IT support labour and
        # project services are not subject to BC PST, only GST.
        gst_tax = self.env['account.tax'].search([
            ('company_id', '=', self.env.company.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 5.0),
            ('country_id.code', '=', 'CA'),
        ], limit=1)
        if not gst_tax:
            _logger.warning(
                'No 5%% CA GST sale tax found for company %s - invoice will be created '
                'without tax. Set up the Canadian Chart of Accounts first.', self.env.company.name)
        return gst_tax

    def _create_customer_invoice(self, amount, label):
        self.ensure_one()
        if amount <= 0:
            raise UserError(_('The invoice amount must be greater than 0.'))
        gst_tax = self._get_gst_tax()
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_id.id,
            'invoice_date': fields.Date.context_today(self),
            'currency_id': self.currency_id.id,
            'ref': f"{self.name} - {self.customer_id.name}",
            'invoice_line_ids': [(0, 0, {
                'name': f"{label} — {self.name} ({dict(self._fields['project_type'].selection).get(self.project_type)})",
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [(6, 0, gst_tax.ids)] if gst_tax else False,
            })],
        })
        return move

    def action_create_deposit_invoice(self):
        self.ensure_one()
        if self.deposit_invoice_id:
            raise UserError(_('A deposit invoice has already been created for this project.'))
        move = self._create_customer_invoice(self.deposit_amount, _('Deposit / Advance Payment'))
        self.deposit_invoice_id = move.id
        return {
            'name': _('Deposit Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
        }

    def action_create_final_invoice(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('The project must be marked Done before creating the final invoice.'))
        if self.final_invoice_id:
            raise UserError(_('A final invoice has already been created for this project.'))
        move = self._create_customer_invoice(self.balance_due, _('Final Invoice'))
        self.write({'final_invoice_id': move.id, 'state': 'invoiced'})
        return {
            'name': _('Final Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
        }

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'name': _('Tasks'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.project.task',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
