# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class ItSupportMonthlySummary(models.Model):
    _name = 'it.support.monthly.summary'
    _description = 'IT Support Monthly Summary'
    _order = 'year desc, month desc, customer_id'
    _rec_name = 'display_name'

    customer_id = fields.Many2one(
        'res.partner', string='Billed To', required=True,
        help='The customer, or their Billing Partner (Reseller) if the underlying '
             'tickets were referred through a subcontract partner.',
    )
    month = fields.Selection([(str(i), str(i)) for i in range(1, 13)], string='Month', required=True)
    year = fields.Integer(string='Year', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    ticket_ids = fields.One2many('it.support.ticket', 'monthly_summary_id', string='Tickets')
    ticket_count = fields.Integer(compute='_compute_totals', string='Ticket Count')

    total_onsite_hours = fields.Float(compute='_compute_totals', string='Onsite Hours')
    total_online_hours = fields.Float(compute='_compute_totals', string='Online Hours')
    total_onsite_amount = fields.Monetary(compute='_compute_totals', string='Onsite Amount')
    total_online_amount = fields.Monetary(compute='_compute_totals', string='Online Amount')
    total_amount = fields.Monetary(compute='_compute_totals', string='Total Amount', store=True)

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('invoiced', 'Invoiced'),
    ], string='Status', default='draft', tracking=True)

    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)

    _unique_customer_month_year = models.Constraint(
        'unique(customer_id, month, year)',
        'A summary for this customer in this month/year already exists!',
    )

    @api.depends('customer_id', 'month', 'year')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.customer_id.name} - {rec.month}/{rec.year}" if rec.customer_id else ''

    @api.depends('ticket_ids.billable_hours', 'ticket_ids.amount_total', 'ticket_ids.session_ids.support_mode')
    def _compute_totals(self):
        for rec in self:
            onsite_hours = onsite_amount = online_hours = online_amount = 0.0
            for ticket in rec.ticket_ids:
                for session in ticket.session_ids.filtered(lambda s: s.state == 'closed'):
                    support_type = session.support_mode_type_id or ticket.support_type_id
                    if not support_type:
                        continue
                    hours = support_type.compute_billable_hours(session.duration)
                    amount = support_type.compute_amount(session.duration)
                    if session.support_mode == 'onsite':
                        onsite_hours += hours
                        onsite_amount += amount
                    else:
                        online_hours += hours
                        online_amount += amount
            rec.total_onsite_hours = onsite_hours
            rec.total_online_hours = online_hours
            rec.total_onsite_amount = onsite_amount
            rec.total_online_amount = online_amount
            rec.total_amount = onsite_amount + online_amount
            rec.ticket_count = len(rec.ticket_ids)

    @api.model
    def generate_for_period(self, month, year, customer_ids=None):
        """Scan completed (done) tickets for the given month/year, group them by
        BILLING partner (the customer's Billing Partner/Reseller if one is set,
        otherwise the customer themselves - see it.support.ticket.billing_partner_id),
        and create/refresh the corresponding monthly summary. This is what lets a single
        reseller's tickets across several different end customers land in one combined
        summary/invoice.
        Called from the monthly cron job or manually.

        customer_ids, if given, still filters by the ticket's actual (end) customer, not
        by billing partner - so a manager can regenerate for one specific end customer's
        tickets even if the resulting summary covers a whole reseller.
        """
        Ticket = self.env['it.support.ticket']
        date_from = fields.Date.to_date(f'{year}-{int(month):02d}-01')
        date_to = date_from + relativedelta(months=1)

        domain = [
            ('state', '=', 'done'),
            ('closed_date', '>=', date_from),
            ('closed_date', '<', date_to),
            ('monthly_summary_id', '=', False),
        ]
        if customer_ids:
            domain.append(('customer_id', 'in', customer_ids))

        tickets = Ticket.search(domain)
        summaries = self.env['it.support.monthly.summary']
        by_billing_partner = {}
        for ticket in tickets:
            by_billing_partner.setdefault(ticket.billing_partner_id.id, []).append(ticket.id)

        for billing_partner_id, ticket_ids in by_billing_partner.items():
            summary = self.search([
                ('customer_id', '=', billing_partner_id),
                ('month', '=', str(int(month))),
                ('year', '=', year),
            ], limit=1)
            if not summary:
                summary = self.create({
                    'customer_id': billing_partner_id,
                    'month': str(int(month)),
                    'year': year,
                })
            Ticket.browse(ticket_ids).write({'monthly_summary_id': summary.id})
            summaries |= summary
        return summaries

    @api.model
    def _cron_generate_previous_month_summary(self):
        """Wrapper called from ir.cron (see data/ir_cron_data.xml).

        IMPORTANT: the ir.cron 'code' field runs through safe_eval, a sandbox Odoo uses
        to restrict Python code embedded directly in XML data - this sandbox FORBIDS the
        IMPORT_NAME opcode (no 'import' of any module, including standard library ones
        like datetime). Therefore all logic that needs imports must live in an actual .py
        file of the module (not subject to this restriction), and ir.cron only calls one
        existing method that contains no import - this is that method.
        """
        today = fields.Date.context_today(self)
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month != 1 else today.year - 1
        self.generate_for_period(prev_month, prev_year)

    def action_open_generate_wizard(self):
        """Open the wizard to manually generate a summary for a chosen month/year
        (e.g. to test billing right away, or to regenerate a month that was missed),
        instead of only relying on the monthly cron job which always targets the
        previous month.
        """
        return {
            'name': _('Generate Monthly Summary'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.generate.summary.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        for rec in self:
            if not rec.ticket_ids:
                raise UserError(_('There are no tickets in this summary.'))
            rec.state = 'confirmed'

    def action_create_invoice(self):
        self.ensure_one()
        if self.state == 'invoiced':
            raise UserError(_('This summary has already been invoiced.'))
        if not self.ticket_ids:
            raise UserError(_('There are no tickets to invoice.'))

        # IT support labour is not subject to BC PST (only tangible goods/certain
        # services are) - only GST applies. If hardware ever gets billed through
        # this flow, it will need its own line with the combined GST+PST tax
        # instead of this one.
        gst_tax = self.env['account.tax'].search([
            ('company_id', '=', self.env.company.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 5.0),
            ('country_id.code', '=', 'CA'),
        ], limit=1)
        if not gst_tax:
            _logger.warning(
                'No 5%% CA GST sale tax found for company %s - invoice lines will be created '
                'without tax. Set up the Canadian Chart of Accounts first.', self.env.company.name)

        invoice_lines = []
        line_ticket_map = []  # keeps track of the ticket matching each created line
        for ticket in self.ticket_ids:
            for session in ticket.session_ids.filtered(lambda s: s.state == 'closed'):
                support_type = session.support_mode_type_id or ticket.support_type_id
                if not support_type:
                    continue
                qty_hours = support_type.compute_billable_hours(session.duration)
                if qty_hours <= 0:
                    continue
                date_label = session.start_time.strftime('%Y-%m-%d') if session.start_time else ''
                mode_label = 'Onsite' if session.support_mode == 'onsite' else 'Online'
                # This summary may be a reseller's combined invoice covering several
                # different end customers - name the actual customer on each line
                # whenever it differs from who the invoice itself is billed to.
                customer_label = (
                    f"{ticket.customer_id.name} — " if ticket.customer_id != self.customer_id else ''
                )
                invoice_lines.append((0, 0, {
                    'name': f"{customer_label}{date_label} — {ticket.subject} (Ticket {ticket.name}, {mode_label})",
                    'quantity': qty_hours,
                    'price_unit': support_type.price_per_hour,
                    'tax_ids': [(6, 0, gst_tax.ids)],
                }))
                line_ticket_map.append(ticket)

        if not invoice_lines:
            raise UserError(_('There is no billable time to invoice.'))

        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_line_ids': invoice_lines,
            'currency_id': self.currency_id.id,
            'ref': f"IT Support {self.month}/{self.year} - {self.customer_id.name}",
        })

        self.write({'invoice_id': move.id, 'state': 'invoiced'})

        # Link invoice_line_id back to the matching ticket (following line creation order)
        # account.move.line usually preserves the creation order in invoice_line_ids
        product_lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        for ticket, line in zip(line_ticket_map, product_lines):
            if not ticket.invoice_line_id:
                ticket.invoice_line_id = line.id

        return {
            'name': _('Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
        }
