# -*- coding: utf-8 -*-
from datetime import date as date_cls
from datetime import datetime

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from . import it_support_fcm_service as fcm_service

# VMTech serves BC's Lower Mainland; resource.calendar's own tz field is left at
# the Odoo default ("UTC", never configured), so the real business timezone is
# hardcoded here rather than trusted from that field.
BUSINESS_TZ = 'America/Vancouver'
SLOT_HOURS = 1.0


class ItSupportBookingRequest(models.Model):
    _name = 'it.support.booking.request'
    _description = 'Website Booking Request (pending customer approval)'
    _order = 'create_date desc'

    company_type = fields.Selection([
        ('person', 'Person'),
        ('company', 'Company'),
    ], string='Customer Type', default='person', required=True)
    name = fields.Char(string='Full Name', required=True)
    company_name = fields.Char(string='Company')
    email = fields.Char(string='Email', required=True)
    phone = fields.Char(string='Phone', required=True)
    requested_start = fields.Datetime(string='Requested Start', required=True)
    # Always 1.0 from the website slot picker; kept as its own field (not
    # hardcoded) since actual on-site work commonly runs longer than the
    # initially requested slot and this may need to reflect that later.
    duration = fields.Float(string='Duration (Hours)', default=1.0, required=True)
    message = fields.Text(string='Message / What do you need help with?')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True)
    partner_id = fields.Many2one('res.partner', string='Created Customer', readonly=True)
    # Filled in by staff when confirming - customers pick a date/time only, VMTech
    # assigns which agent handles it (and calls/emails to renegotiate the time if
    # nobody is free then, since slots are not hard-blocked against each other).
    assigned_agent_id = fields.Many2one(
        'res.users', string='Assigned Agent',
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
    )
    ticket_id = fields.Many2one(
        'it.support.ticket', string='Created Ticket', readonly=True, copy=False,
        help='Set when a Manager converts this booking into a ticket from the Desktop/Mobile '
             'Agent app (or manually from this form) - lets staff see at a glance that a booking '
             'was already actioned and where it ended up.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._notify_managers_new_booking()
        return records

    def _notify_managers_new_booking(self):
        """New website booking -> alert Managers the same way it.support.ticket
        alerts on-duty agents for a new ticket: FCM push (Mobile Agent App, works
        even if the app is closed/backgrounded) + a bus.bus event on the shared
        dispatch channel (Desktop Agent App's already-open long-poll subscription -
        no separate channel/subscription needed since it already listens there for
        new tickets)."""
        self.ensure_one()
        manager_group = self.env.ref('it_support_management.group_it_support_manager')
        # sudo() required: this runs from the public website form (auth='public'),
        # and the public user has no read access to res.users - an un-sudo'd search
        # silently returns an empty recordset (no AccessError) rather than raising,
        # so this would otherwise fail completely silently with no notification and
        # no error in the logs.
        managers = self.env['res.users'].sudo().search([('group_ids', 'in', manager_group.id)])
        if not managers:
            return

        contact_label = f'{self.company_name} ({self.name})' if self.company_name else self.name

        tokens = [
            d.fcm_token for d in self.env['it.support.agent.device'].sudo().search(
                [('agent_id', 'in', managers.ids)]
            ) if d.fcm_token
        ]
        if tokens:
            result = fcm_service.send_fcm_notification(
                tokens,
                title='📅 New Booking Request',
                body=contact_label,
                data={'event': 'new_booking', 'booking_id': str(self.id)},
            )
            if result.get('invalid_tokens'):
                self.env['it.support.agent.device'].sudo().search([
                    ('fcm_token', 'in', result['invalid_tokens']),
                ]).unlink()

        self.env['bus.bus']._sendone(
            self.env['it.support.ticket']._get_dispatch_channel(), 'it_support_new_booking', {
                'booking_id': self.id,
                'contact': contact_label,
            },
        )

    def action_confirm(self):
        """Duyệt yêu cầu: tìm Customer đã có (khớp theo email) hoặc tạo mới,
        gắn vào request, chuyển trạng thái sang Confirmed."""
        for rec in self:
            if rec.state != 'pending':
                continue
            partner = self.env['res.partner'].sudo().search([('email', '=', rec.email)], limit=1)
            if not partner:
                is_company = rec.company_type == 'company'
                partner = self.env['res.partner'].sudo().create({
                    'name': (rec.company_name or rec.name) if is_company else rec.name,
                    'is_company': is_company,
                    'email': rec.email,
                    'phone': rec.phone,
                })
            rec.write({'state': 'confirmed', 'partner_id': partner.id})
        return True

    def action_reject(self):
        for rec in self:
            if rec.state == 'pending':
                rec.write({'state': 'rejected'})
        return True

    def _format_requested_start(self):
        self.ensure_one()
        if not self.requested_start:
            return ''
        tz = self._get_business_tz()
        local_dt = pytz.utc.localize(self.requested_start).astimezone(tz)
        return local_dt.strftime('%A, %B %d, %Y at %I:%M %p (%Z)')

    def _build_ticket_description(self):
        self.ensure_one()
        lines = [
            '<p>Booking request submitted via the website.</p>',
            '<p><strong>Requested time:</strong> %s (%.1fh)<br/>'
            '<strong>Contact:</strong> %s - %s - %s</p>' % (
                self._format_requested_start(), self.duration,
                self.name, self.phone, self.email,
            ),
        ]
        if self.message:
            lines.append('<p><strong>Message:</strong><br/>%s</p>' % self.message.replace('\n', '<br/>'))
        return ''.join(lines)

    def action_confirm_and_create_ticket(self):
        """Manager-only action (called from the Odoo backend button, or from the
        Desktop/Mobile Agent app via the API): confirms the booking (creating/
        linking the Customer if needed, same as action_confirm) and opens an
        initial ticket from it in one step - meant to be used right after the
        manager has called the customer to confirm the details."""
        self.ensure_one()
        if self.state == 'rejected':
            raise UserError(_('This booking request was already rejected.'))
        if self.ticket_id:
            raise UserError(_('A ticket was already created from this booking request.'))
        if self.state == 'pending':
            self.action_confirm()
        ticket = self.env['it.support.ticket'].sudo().create({
            'customer_id': self.partner_id.id,
            'subject': _('Booking Request - %s') % (self.company_name or self.name),
            'description': self._build_ticket_description(),
            'priority': '1',
        })
        self.ticket_id = ticket.id
        return ticket

    @api.model
    def _get_business_tz(self):
        return pytz.timezone(BUSINESS_TZ)

    @api.model
    def get_today_str(self):
        """'Today' in the business timezone (America/Vancouver), as YYYY-MM-DD.
        Deliberately NOT date.today()/datetime.now() with no tz argument - those
        resolve to whatever the server process/OS considers "local", which on a
        dev machine can silently disagree with the real wall-clock date (e.g. a
        service process defaulting to UTC while the desktop clock is Vietnam
        time) and drift the picker's default date by a day.
        """
        return datetime.now(pytz.utc).astimezone(self._get_business_tz()).date().isoformat()

    @api.model
    def get_available_slots(self, date_str):
        """Return the bookable 1h slots for the given local date (YYYY-MM-DD) as
        [{'value': '09:00', 'label': '9:00 AM'}, ...], based on the company's
        working calendar (res.company.resource_calendar_id) - independent of the
        IT agent duty roster (it.support.duty.schedule). Already-requested slots
        are NOT excluded: VMTech resolves any double-booking by contacting the
        customer to agree on a different time, rather than blocking the slot
        outright.
        """
        try:
            day = date_cls.fromisoformat(date_str)
        except (TypeError, ValueError):
            return []

        calendar = self.env.company.sudo().resource_calendar_id
        if not calendar:
            return []

        weekday = day.weekday()  # Monday=0 .. Sunday=6, same convention as attendance.dayofweek
        attendances = calendar.sudo().attendance_ids.filtered(
            lambda a: int(a.dayofweek) == weekday and a.day_period != 'lunch'
        )
        if not attendances:
            return []

        tz = self._get_business_tz()
        now_local = datetime.now(pytz.utc).astimezone(tz)
        is_today = day == now_local.date()
        now_hour_float = now_local.hour + now_local.minute / 60.0

        seen = set()
        for att in attendances:
            start_hour = att.hour_from
            while start_hour + SLOT_HOURS <= att.hour_to + 1e-6:
                if not (is_today and start_hour <= now_hour_float):
                    seen.add(round(start_hour, 2))
                start_hour += SLOT_HOURS

        slots = []
        for hour_float in sorted(seen):
            hh = int(hour_float)
            mm = int(round((hour_float - hh) * 60))
            period = 'AM' if hh < 12 else 'PM'
            hh12 = hh % 12 or 12
            slots.append({
                'value': '%02d:%02d' % (hh, mm),
                'label': '%d:%02d %s' % (hh12, mm, period),
            })
        return slots

    @api.model
    def local_to_utc_datetime(self, date_str, hour_str):
        """Combine a local date (YYYY-MM-DD) + local 'HH:MM' time, interpreted in
        the business timezone, into a naive UTC datetime for a Datetime field."""
        tz = self._get_business_tz()
        naive_local = datetime.strptime('%s %s' % (date_str, hour_str), '%Y-%m-%d %H:%M')
        localized = tz.localize(naive_local)
        return localized.astimezone(pytz.utc).replace(tzinfo=None)
