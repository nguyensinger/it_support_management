# -*- coding: utf-8 -*-
import logging

from werkzeug.urls import url_encode

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class ItSupportWebsiteBooking(http.Controller):
    """Public 'Booking' page on the VMTech website.

    Kept as our own explicit controller/route instead of the generic Odoo
    Website Form snippet (/website/form/<model>), because that generic route
    only works for models flagged website_form_access=True on ir.model - a
    flag normally set by picking the model in the Form snippet's Action
    dropdown in Developer Mode, which is per-database UI configuration and
    would have to be redone by hand on every environment (local demo site,
    production VM, ...). A dedicated route ships with the module and behaves
    the same everywhere.
    """

    REQUIRED_FIELDS = ['name', 'email', 'phone', 'street', 'city', 'state_id', 'zip', 'date', 'start_hour']
    RECAPTCHA_ACTION = 'booking'

    @http.route('/booking', type='http', auth='public', website=True, sitemap=True)
    def booking_page(self, **kw):
        Booking = request.env['it.support.booking.request']
        today_str = Booking.get_today_str()
        selected_date = kw.get('date') or today_str
        slots = Booking.get_available_slots(selected_date)

        # Logged-in (portal) customers get their contact info prefilled; new
        # visitors aren't required to log in or have an account at all. Query
        # params (e.g. re-showing the form after a validation error) still win,
        # so we don't clobber what the visitor just typed.
        formatted = dict(self._get_partner_prefill())
        formatted.update(kw)

        user = request.env.user
        is_logged_in = not user._is_public()

        return request.render('it_support_management.website_booking_page', {
            'success': kw.get('success'),
            'error_fields': (kw.get('error_fields') or '').split(',') if kw.get('error_fields') else [],
            'formatted': formatted,
            'today_str': today_str,
            'selected_date': selected_date,
            'slots': slots,
            # VMTech only serves BC's Lower Mainland (see BUSINESS_TZ in the model) -
            # Province is a dropdown of Canadian provinces only, no Country field at all.
            'provinces': request.env['res.country.state'].sudo().search(
                [('country_id', '=', request.env.ref('base.ca').id)], order='name'
            ),
            'is_logged_in': is_logged_in,
            'has_payment_token': is_logged_in and self._get_person_payment_token(user.partner_id).exists(),
        })

    @staticmethod
    def _get_person_payment_token(partner):
        """Individual customers need their own saved card - deliberately matched
        on the exact partner, not commercial_partner_id (which would let a card
        saved by one person "cover" a completely different person just because
        they happen to share a parent contact - not the sharing behaviour we
        want for individual bookings, unlike Company-side charging elsewhere in
        Odoo's own token-ownership checks)."""
        return request.env['payment.token'].sudo().search([
            ('partner_id', '=', partner.id),
        ], limit=1, order='create_date desc')

    @staticmethod
    def _get_partner_prefill():
        user = request.env.user
        if user._is_public():
            return {}
        partner = user.partner_id
        commercial = partner.commercial_partner_id
        return {
            'name': partner.name or '',
            'email': partner.email or '',
            'phone': partner.phone or '',
            'company_name': commercial.name if commercial and commercial != partner else '',
            'company_type': 'company' if partner.is_company else 'person',
            'street': partner.street or '',
            'city': partner.city or '',
            'state_id': str(partner.state_id.id) if partner.state_id else '',
            'zip': partner.zip or '',
        }

    @http.route('/booking/submit', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def booking_submit(self, **post):
        Booking = request.env['it.support.booking.request']

        company_type = post.get('company_type') if post.get('company_type') in ('person', 'company') else 'person'
        selected_date = post.get('date') or Booking.get_today_str()
        start_hour = post.get('start_hour', '')

        def redirect_with_error(error_fields):
            return request.redirect('/booking?%s' % url_encode({
                'date': selected_date,
                'error_fields': ','.join(error_fields),
                'name': post.get('name', ''),
                'company_name': post.get('company_name', ''),
                'email': post.get('email', ''),
                'phone': post.get('phone', ''),
                'street': post.get('street', ''),
                'city': post.get('city', ''),
                'state_id': post.get('state_id', ''),
                'zip': post.get('zip', ''),
                'message': post.get('message', ''),
                'start_hour': start_hour,
                'company_type': company_type,
            }))

        try:
            request.env['ir.http']._verify_request_recaptcha_token(self.RECAPTCHA_ACTION)
        except (UserError, ValidationError):
            # Wrong/expired/missing token (bot, or a stale page left open too long) -
            # re-show the form rather than a hard crash.
            return redirect_with_error(['captcha'])

        missing = [f for f in self.REQUIRED_FIELDS if not (post.get(f) or '').strip()]

        state_id = False
        if 'state_id' not in missing:
            # Confirm it's actually one of the offered Canadian provinces (defends
            # against a tampered/non-numeric value, not just a missing one).
            try:
                state_id = request.env['res.country.state'].sudo().search([
                    ('id', '=', int(post.get('state_id'))),
                    ('country_id', '=', request.env.ref('base.ca').id),
                ], limit=1)
            except ValueError:
                state_id = False
            if not state_id:
                missing.append('state_id')

        valid_hours = {s['value'] for s in Booking.get_available_slots(selected_date)}
        if not missing and start_hour not in valid_hours:
            # Stale page (slots changed) or tampered value - re-show the form
            # rather than trusting a slot we can no longer vouch for.
            missing = ['start_hour']

        if missing:
            return redirect_with_error(missing)

        # Individual customers must be logged in with a saved card before we'll
        # take the booking - Company customers are unaffected, they stay on the
        # existing invoice/manual-payment process. Nothing is charged here; the
        # token is just attached so staff can charge it later against the real
        # invoice once the work is done.
        payment_token = request.env['payment.token']
        if company_type == 'person':
            user = request.env.user
            if user._is_public():
                return redirect_with_error(['login_required'])
            payment_token = self._get_person_payment_token(user.partner_id)
            if not payment_token:
                return redirect_with_error(['card_required'])

        requested_start = Booking.local_to_utc_datetime(selected_date, start_hour)
        Booking.create({
            'company_type': company_type,
            'name': post.get('name', '').strip(),
            'company_name': (post.get('company_name') or '').strip(),
            'email': post.get('email', '').strip(),
            'phone': post.get('phone', '').strip(),
            'street': post.get('street', '').strip(),
            'city': post.get('city', '').strip(),
            'state_id': state_id.id,
            'zip': post.get('zip', '').strip(),
            'requested_start': requested_start,
            'duration': 1.0,
            'message': (post.get('message') or '').strip(),
            'payment_token_id': payment_token.id if payment_token else False,
        })

        return request.redirect('/booking?success=1')
