# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models, _


class ItCustomerDevice(models.Model):
    _name = 'it.customer.device'
    _description = 'IT Customer Device'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Hostname', required=True, tracking=True)
    customer_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain="[('is_company', '=', True)]", tracking=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one(
        'it.support.end.user', string='User',
        domain="[('customer_id', '=', customer_id)]", tracking=True,
    )

    # Hardware / software info — automatically updated by the desktop agent via API
    serial_number = fields.Char(string='Serial Number')
    os_info = fields.Char(string='Operating System')
    cpu_info = fields.Char(string='CPU')
    ram_gb = fields.Float(string='RAM (GB)')
    disk_info = fields.Char(string='Storage')
    mac_address = fields.Char(string='MAC Address')
    ip_address = fields.Char(string='IP Address (LAN)')

    # Remote support
    ultraview_id = fields.Char(string='UltraViewer ID', tracking=True)
    agent_api_key = fields.Char(
        string='Agent API Key', copy=False,
        help='Dedicated API key used by this device\'s desktop agent to call the API.'
    )

    install_date = fields.Date(string='Agent Install Date', default=fields.Date.context_today)
    last_seen = fields.Datetime(string='Last Seen (heartbeat)')
    state = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('unknown', 'Unknown'),
    ], string='Status', default='unknown', compute='_compute_state', store=True)

    ticket_ids = fields.One2many('it.support.ticket', 'device_id', string='Related Tickets')
    ticket_count = fields.Integer(compute='_compute_ticket_count', string='Ticket Count')
    active = fields.Boolean(default=True)

    _ultraview_id_unique = models.Constraint(
        'unique(ultraview_id)',
        'This UltraViewer ID is already assigned to another device!',
    )

    @api.depends('last_seen')
    def _compute_state(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.last_seen:
                rec.state = 'unknown'
            else:
                delta_minutes = (now - rec.last_seen).total_seconds() / 60.0
                rec.state = 'online' if delta_minutes <= 5 else 'offline'

    @api.depends('ticket_ids')
    def _compute_ticket_count(self):
        for rec in self:
            rec.ticket_count = len(rec.ticket_ids)

    def action_view_tickets(self):
        self.ensure_one()
        return {
            'name': _('Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.ticket',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
            'context': {'default_device_id': self.id, 'default_customer_id': self.customer_id.id},
        }

    def _ensure_agent_api_key(self):
        """Mint this device's own dedicated API key if it doesn't have one yet -
        called right after a successful /api/v1/device/pair. This is the ONLY
        time the plaintext value is ever available; the client stores it locally
        and uses it for every call afterward (heartbeat, tickets, chat), so the
        end user never has to know or type any API key themselves."""
        self.ensure_one()
        if not self.agent_api_key:
            self.agent_api_key = secrets.token_hex(32)
        return self.agent_api_key

    def heartbeat(self, vals=None):
        """Called from the API when the desktop agent sends a heartbeat signal.
        vals: dict of hardware fields that may be updated alongside (optional).
        """
        self.ensure_one()
        update_vals = {'last_seen': fields.Datetime.now()}
        if vals:
            allowed = {'os_info', 'cpu_info', 'ram_gb', 'disk_info', 'mac_address', 'ip_address', 'ultraview_id'}
            update_vals.update({k: v for k, v in vals.items() if k in allowed})
        self.write(update_vals)
        return True
