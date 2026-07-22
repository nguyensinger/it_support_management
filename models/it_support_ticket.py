# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from . import it_support_fcm_service as fcm_service


class ItSupportTicket(models.Model):
    _name = 'it.support.ticket'
    _description = 'IT Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Ticket No.', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('it.support.ticket') or 'New',
    )

    # Relations
    customer_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain="[('is_company', '=', True)]", tracking=True,
    )
    device_id = fields.Many2one(
        'it.customer.device', string='Device',
        domain="[('customer_id', '=', customer_id)]", tracking=True,
    )
    end_user_id = fields.Many2one(
        'it.support.end.user', string='Requested By',
        domain="[('customer_id', '=', customer_id)]", tracking=True,
    )

    subject = fields.Char(string='Subject', required=True, tracking=True)
    description = fields.Html(string='Description')

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority', default='1', tracking=True)

    state = fields.Selection([
        ('new', 'New'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('paused', 'Paused'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='new', tracking=True, group_expand='_group_expand_states')

    agent_id = fields.Many2one('res.users', string='IT Support Agent', tracking=True)
    assigned_date = fields.Datetime(string='Assigned Date', readonly=True)
    closed_date = fields.Datetime(string='Closed Date', readonly=True)

    # Support type & pricing
    support_type_id = fields.Many2one(
        'it.support.type', string='Support Type', tracking=True,
        help='Default support type when the ticket is created (the agent may handle it '
             'differently in practice).',
    )
    currency_id = fields.Many2one(related='support_type_id.currency_id', string='Currency', readonly=True)

    # Sessions (start/end) — a ticket can have multiple sessions
    session_ids = fields.One2many('it.support.session', 'ticket_id', string='Working Sessions')
    session_count = fields.Integer(compute='_compute_session_stats', string='Session Count')
    has_running_session = fields.Boolean(
        compute='_compute_session_stats', string='Has Running Session',
        help='True if the ticket currently has a session in "running" state (started but not '
             'ended yet). Used to show/hide the Start/End buttons on the form.',
    )

    total_duration = fields.Float(
        string='Total Time Worked (hours)', compute='_compute_session_stats', store=True,
        help='Total actual time (in hours) computed from the start/end sessions.',
    )
    billable_hours = fields.Float(
        string='Billable Hours', compute='_compute_billing', store=True,
        help='Total hours after applying each session\'s billing block rules.',
    )
    amount_total = fields.Monetary(
        string='Amount', compute='_compute_billing', store=True, currency_field='currency_id',
    )
    actual_support_modes = fields.Char(
        string='Actual Mode(s) Billed', compute='_compute_billing', store=True,
        help='The support mode(s) actually used for billing, taken from each closed '
             'session\'s Actual Mode - NOT the initial Support Type set when the ticket '
             'was created. The agent may handle a ticket differently than initially '
             'planned (e.g. ticket created as Onsite but actually resolved Online), and '
             'billing always follows what was actually done.',
    )

    invoice_line_id = fields.Many2one('account.move.line', string='Invoice Line', readonly=True, copy=False)
    invoice_id = fields.Many2one(
        'account.move', string='Invoice', related='invoice_line_id.move_id', readonly=True, store=True,
    )
    monthly_summary_id = fields.Many2one(
        'it.support.monthly.summary', string='Monthly Summary', readonly=True, copy=False,
    )
    is_invoiced = fields.Boolean(compute='_compute_billing', string='Invoiced', store=True)


    # ---------- SLA ----------
    sla_id = fields.Many2one(
        'it.support.sla', string='SLA Policy', compute='_compute_sla', store=True,
    )
    sla_response_deadline = fields.Datetime(string='Response Deadline', compute='_compute_sla', store=True)
    sla_resolution_deadline = fields.Datetime(string='Resolution Deadline', compute='_compute_sla', store=True)

    first_response_date = fields.Datetime(string='First Response Date', readonly=True)
    sla_response_status = fields.Selection([
        ('pending', 'Pending'),
        ('ok', 'On Time'),
        ('breached', 'Breached'),
    ], string='Response SLA', compute='_compute_sla_status', store=True, default='pending')
    sla_resolution_status = fields.Selection([
        ('pending', 'Pending'),
        ('ok', 'On Time'),
        ('breached', 'Breached'),
    ], string='Resolution SLA', compute='_compute_sla_status', store=True, default='pending')

    active = fields.Boolean(default=True)

    # ---------- Realtime (bus.bus) ----------
    def _get_ticket_channel(self):
        """Dedicated channel for this ticket - used by the mobile app / desktop agent to
        subscribe and receive realtime updates (new chat, status change, session start/end).
        """
        self.ensure_one()
        return f'it_support_ticket_{self.id}'

    @api.model
    def _get_dispatch_channel(self):
        """Shared channel for on-duty agents to be notified of new/unassigned tickets."""
        return 'it_support_dispatch'

    def _auto_assign_on_duty_agent(self):
        """Automatically assign this newly-created ticket to an agent, following this
        priority order:
          1. The customer's preferred agent (res.partner.preferred_agent_id), but ONLY
             if that agent is currently on duty according to the duty schedule.
          2. Whoever is on duty right now (any agent), regardless of customer.
          3. If nobody is on duty (e.g. outside scheduled hours, or no schedule
             configured), leave the ticket unassigned - an agent can still pick it up
             manually via "Assign to Me", same as before this feature was added.
        """
        self.ensure_one()
        if self.agent_id:
            return  # already assigned (e.g. created directly with an agent_id) - don't override

        Schedule = self.env['it.support.duty.schedule']
        on_duty_agent = Schedule.get_agent_on_duty()
        if not on_duty_agent:
            return  # nobody on duty right now - leave unassigned for manual pickup

        preferred_agent = self.customer_id.preferred_agent_id
        if preferred_agent and preferred_agent.id == on_duty_agent.id:
            chosen_agent = preferred_agent
        else:
            chosen_agent = on_duty_agent

        self.write({
            'agent_id': chosen_agent.id,
            'state': 'assigned',
            'assigned_date': fields.Datetime.now(),
        })


    def _get_agent_fcm_tokens(self, agents):
        """Lấy tất cả FCM token hợp lệ của danh sách agents (res.users recordset)."""
        if not agents:
            return []
        devices = self.env['it.support.agent.device'].sudo().search([
            ('agent_id', 'in', agents.ids),
        ])
        return [d.fcm_token for d in devices if d.fcm_token]

    def _send_fcm_to_agents(self, agents, title, body, data=None):
        """Gửi FCM push notification đến tất cả thiết bị của agents.
        Tự động xoá token không còn hợp lệ (app uninstall) sau khi gửi.
        """
        tokens = self._get_agent_fcm_tokens(agents)
        if not tokens:
            return
        result = fcm_service.send_fcm_notification(tokens, title, body, data=data)
        # Dọn dẹp token không còn hợp lệ
        if result.get('invalid_tokens'):
            self.env['it.support.agent.device'].sudo().search([
                ('fcm_token', 'in', result['invalid_tokens']),
            ]).unlink()

    def _bus_notify(self, event_type, payload=None):
        """Broadcast a realtime event on this ticket's channel."""
        for rec in self:
            data = {'event': event_type, 'ticket_id': rec.id, 'ticket_name': rec.name}
            if payload:
                data.update(payload)
            self.env['bus.bus']._sendone(rec._get_ticket_channel(), 'it_support_update', data)

    @api.model
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._auto_assign_on_duty_agent()
            # Notify on-duty agents of the new ticket (especially if still unassigned)
            self.env['bus.bus']._sendone(rec._get_dispatch_channel(), 'it_support_new_ticket', {
                'ticket_id': rec.id,
                'ticket_name': rec.name,
                'subject': rec.subject,
                'customer': rec.customer_id.name,
                'priority': rec.priority,
            })
            # FCM push notification — gửi đến agent được assign (hoặc tất cả agent on-duty nếu chưa assign)
            if rec.agent_id:
                notify_agents = rec.agent_id
            else:
                agent_group = self.env.ref('it_support_management.group_it_support_agent')
                notify_agents = self.env['res.users'].search([('group_ids', 'in', agent_group.id)])
            rec._send_fcm_to_agents(
                notify_agents,
                title=f'🎫 Ticket mới — {rec.customer_id.name}',
                body=rec.subject,
                data={'ticket_id': str(rec.id), 'event': 'new_ticket'},
            )
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'state' in vals or 'agent_id' in vals:
            for rec in self:
                rec._bus_notify('state_changed', {
                    'state': rec.state,
                    'agent_id': rec.agent_id.id,
                    'agent_name': rec.agent_id.name if rec.agent_id else None,
                })
        return result

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        # Broadcast a realtime event as soon as there's a new message (chat), so the
        # desktop agent / mobile app updates instantly without having to poll constantly.
        if message.message_type == 'comment':
            self._bus_notify('new_message', {
                'message_id': message.id,
                'author': message.author_id.name,
                'body': message.body,
                'date': str(message.date),
            })
            # Track first response date for SLA — only record the FIRST agent reply
            if (not self.first_response_date and
                    message.author_id and
                    message.author_id != self.customer_id and
                    self.agent_id and message.author_id == self.agent_id.partner_id):
                self.sudo().write({'first_response_date': fields.Datetime.now()})
        return message

    def _notify_agents_new_customer_message(self, body):
        """Called when the customer (via the desktop agent) sends a new chat message.
        Ensures the assigned agent (or all IT support agents if the ticket is unassigned)
        receives an EMAIL notification - using Odoo's standard follower + mail notification
        mechanism (mail.thread) rather than sending email manually, to avoid duplicating
        or conflicting with the existing mail server / template configuration.
        """
        self.ensure_one()
        if self.agent_id:
            recipients = self.agent_id.partner_id
        else:
            # Not assigned yet - notify all on-duty agents (Agent group) so anyone available
            # can pick it up. Uses res.users.search() with a domain on group_ids (a field
            # confirmed to exist on res.users in Odoo 19) rather than the reverse field on
            # res.groups (users/user_ids), to avoid relying on a field name that isn't
            # confirmed with certainty.
            agent_group = self.env.ref('it_support_management.group_it_support_agent')
            agents = self.env['res.users'].search([('group_ids', 'in', agent_group.id)])
            recipients = agents.mapped('partner_id')
        if recipients:
            # Add the agents as followers if not already, so they keep receiving
            # notifications for further messages on this ticket, not just the first one.
            self.message_subscribe(partner_ids=recipients.ids)

        # Đặt author_id = partner của khách hàng (customer_id - công ty/người liên hệ
        # chính trên Odoo) thay vì để Odoo tự gán current user của API key (thường là
        # user kỹ thuật/Administrator). Điều này giúp message_ids.author_id.name trả về
        # đúng tên khách hàng thay vì "Administrator" khi hiển thị trên agent app.
        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=recipients.ids if recipients else [],
            author_id=self.customer_id.id or None,
        )
        # FCM push notification cho agent — tin nhắn từ khách hàng
        if self.agent_id:
            notify_agents = self.agent_id
        else:
            agent_group = self.env.ref('it_support_management.group_it_support_agent')
            notify_agents = self.env['res.users'].search([('group_ids', 'in', agent_group.id)])
        plain_body = body.replace('<p>', '').replace('</p>', '').strip() if body else ''
        short_body = plain_body[:100] + '…' if len(plain_body) > 100 else plain_body
        self._send_fcm_to_agents(
            notify_agents,
            title=f'💬 Tin nhắn mới — {self.name}',
            body=short_body or '(tin nhắn mới)',
            data={'ticket_id': str(self.id), 'event': 'new_message'},
        )
        # Realtime notification cho Desktop Agent App (khác cơ chế FCM ở trên vốn
        # chỉ dành cho Mobile Agent App). Phát trên dispatch channel (channel chung
        # mọi agent đang trực đều subscribe kể cả khi đang ở màn hình danh sách,
        # chưa mở đúng ticket này) kèm agent_id để client tự lọc, chỉ hiện thông
        # báo desktop cho đúng agent đang được assign ticket đó.
        self.env['bus.bus']._sendone(self._get_dispatch_channel(), 'it_support_customer_message', {
            'ticket_id': self.id,
            'ticket_name': self.name,
            'customer': self.customer_id.name,
            'agent_id': self.agent_id.id if self.agent_id else None,
            'preview': short_body or '(tin nhắn mới)',
        })


    # ---------- SLA Compute ----------
    @api.depends('priority', 'create_date')
    def _compute_sla(self):
        SLA = self.env['it.support.sla']
        for rec in self:
            sla = SLA.search([('priority', '=', rec.priority), ('active', '=', True)], limit=1)
            rec.sla_id = sla.id if sla else False
            if sla and rec.create_date:
                from datetime import timedelta
                rec.sla_response_deadline = rec.create_date + timedelta(hours=sla.response_time_hours)
                rec.sla_resolution_deadline = rec.create_date + timedelta(hours=sla.resolution_time_hours)
            else:
                rec.sla_response_deadline = False
                rec.sla_resolution_deadline = False

    @api.depends('sla_response_deadline', 'sla_resolution_deadline',
                 'first_response_date', 'state', 'closed_date')
    def _compute_sla_status(self):
        now = fields.Datetime.now()
        for rec in self:
            # Response SLA
            if rec.first_response_date and rec.sla_response_deadline:
                if rec.first_response_date <= rec.sla_response_deadline:
                    rec.sla_response_status = 'ok'
                else:
                    rec.sla_response_status = 'breached'
            elif rec.sla_response_deadline and now > rec.sla_response_deadline:
                rec.sla_response_status = 'breached'
            else:
                rec.sla_response_status = 'pending'

            # Resolution SLA
            if rec.state in ('done', 'cancelled') and rec.closed_date and rec.sla_resolution_deadline:
                if rec.closed_date <= rec.sla_resolution_deadline:
                    rec.sla_resolution_status = 'ok'
                else:
                    rec.sla_resolution_status = 'breached'
            elif rec.sla_resolution_deadline and now > rec.sla_resolution_deadline:
                rec.sla_resolution_status = 'breached'
            else:
                rec.sla_resolution_status = 'pending'

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, label in self._fields['state'].selection]

    @api.depends('session_ids.duration', 'session_ids.state')
    def _compute_session_stats(self):
        for rec in self:
            closed_sessions = rec.session_ids.filtered(lambda s: s.state == 'closed')
            rec.total_duration = sum(closed_sessions.mapped('duration'))
            rec.session_count = len(rec.session_ids)
            rec.has_running_session = bool(rec.session_ids.filtered(lambda s: s.state == 'running'))

    @api.depends('session_ids.duration', 'session_ids.state', 'session_ids.support_mode',
                 'session_ids.support_mode_type_id.price_per_hour',
                 'session_ids.support_mode_type_id.first_block_minutes',
                 'session_ids.support_mode_type_id.block_minutes',
                 'session_ids.support_mode_type_id.min_charge_blocks',
                 'support_type_id', 'support_type_id.price_per_hour',
                 'support_type_id.first_block_minutes', 'support_type_id.block_minutes',
                 'support_type_id.min_charge_blocks', 'invoice_line_id')
    def _compute_billing(self):
        for rec in self:
            closed_sessions = rec.session_ids.filtered(lambda s: s.state == 'closed')
            billable_hours = 0.0
            amount = 0.0
            modes_used = []
            # Billed per session, since each session may be onsite or online independently
            for session in closed_sessions:
                support_type = session.support_mode_type_id or rec.support_type_id
                if not support_type:
                    continue
                billable_hours += support_type.compute_billable_hours(session.duration)
                amount += support_type.compute_amount(session.duration)
                mode_label = dict(session._fields['support_mode'].selection).get(session.support_mode)
                if mode_label and mode_label not in modes_used:
                    modes_used.append(mode_label)
            rec.billable_hours = billable_hours
            rec.amount_total = amount
            rec.actual_support_modes = ', '.join(modes_used) if modes_used else False
            rec.is_invoiced = bool(rec.invoice_line_id)

    # ---------- Actions ----------
    def action_assign_to_me(self):
        self.ensure_one()
        self.write({
            'agent_id': self.env.user.id,
            'state': 'assigned',
            'assigned_date': fields.Datetime.now(),
        })

    def action_start_progress(self):
        self.ensure_one()
        if self.state not in ('new', 'assigned', 'paused'):
            raise UserError(_('You can only start working on a ticket from New/Assigned/Paused status.'))
        self.write({'state': 'in_progress'})

    def action_pause(self):
        self.ensure_one()
        self.write({'state': 'paused'})
        # Close any running session when pausing. This is a system-triggered
        # close (the agent didn't explicitly hit "End Session"), so it does not
        # require a work note / resolution status - see _auto_close_session.
        running = self.session_ids.filtered(lambda s: s.state == 'running')
        running._auto_close_session()

    def action_done(self):
        self.ensure_one()
        running = self.session_ids.filtered(lambda s: s.state == 'running')
        if running:
            # System-triggered close (agent marked ticket Done without an explicit
            # End Session first) - no note/resolution_status required here.
            running._auto_close_session()
        self.write({'state': 'done', 'closed_date': fields.Datetime.now()})

    def action_cancel(self):
        self.ensure_one()
        running = self.session_ids.filtered(lambda s: s.state == 'running')
        # System-triggered close - no note/resolution_status required here.
        running._auto_close_session()
        self.write({'state': 'cancelled'})

    def action_recompute_billing(self):
        """Force-recompute billable_hours / amount_total for the selected tickets.

        Needed after changing pricing on it.support.type (price_per_hour, block
        sizes, etc.): _compute_billing is a stored compute field, so Odoo only
        re-evaluates it automatically when one of its @api.depends fields actually
        changes going forward. It does NOT retroactively recompute values that were
        already stored before the pricing was edited. This action lets a manager
        manually refresh old tickets to reflect the current pricing, using Odoo's
        documented way of forcing a stored compute field to recompute.
        """
        billable_hours_field = self._fields['billable_hours']
        amount_total_field = self._fields['amount_total']
        self.env.add_to_compute(billable_hours_field, self)
        self.env.add_to_compute(amount_total_field, self)
        self._recompute_recordset(['billable_hours', 'amount_total'])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Billing Recomputed'),
                'message': _('%d ticket(s) updated with current pricing.') % len(self),
                'type': 'success',
            },
        }

    def action_start_session(self, support_mode=None):
        """Called from the mobile app when the agent starts working on a ticket (Start session)."""
        self.ensure_one()
        if self.session_ids.filtered(lambda s: s.state == 'running'):
            raise UserError(_('This ticket already has an unfinished working session.'))
        session = self.env['it.support.session'].create({
            'ticket_id': self.id,
            'agent_id': self.env.user.id,
            'start_time': fields.Datetime.now(),
            'support_mode': support_mode or (self.support_type_id.mode if self.support_type_id else 'online'),
            'state': 'running',
        })
        if self.state in ('new', 'assigned', 'paused'):
            self.write({'state': 'in_progress'})
        if not self.agent_id:
            self.agent_id = self.env.user.id
        self._bus_notify('session_started', {
            'session_id': session.id,
            'agent_name': self.env.user.name,
            'start_time': str(session.start_time),
        })
        return session

    def action_send_reply(self, body):
        """Send a reply to the customer for this ticket - posted to the message
        thread (mail.thread), visible to the customer via the Desktop Client
        App's Ticket Chat tab and by email notification. Reuses the existing
        message_post() override above, which automatically records
        first_response_date the first time an agent's message is posted -
        so a reply here counts as the ticket's first response for SLA purposes,
        exactly the same as a message sent through the regular chat.
        """
        self.ensure_one()
        if not body or not body.strip():
            raise UserError(_('Reply content cannot be empty.'))
        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return True

    def action_end_session(self, note=None, resolution_status=None):
        """Called from the mobile app when the agent finishes working (End session).
        Both `note` and `resolution_status` are required - enforced down in
        it.support.session.action_end_session. The work note is ALSO sent to the
        customer as a reply (see action_send_reply) - the agent only types it once,
        and it serves both as the internal session record and the customer-facing
        update.
        """
        self.ensure_one()
        running = self.session_ids.filtered(lambda s: s.state == 'running')
        if not running:
            raise UserError(_('There is no running working session for this ticket.'))
        running.action_end_session(note=note, resolution_status=resolution_status)
        self.action_send_reply(note)
        self._bus_notify('session_ended', {
            'duration': running.duration,
            'total_duration': self.total_duration,
        })
        return True
