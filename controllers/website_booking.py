# -*- coding: utf-8 -*-
import logging

from werkzeug.urls import url_encode

from odoo import http
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

    REQUIRED_FIELDS = ['name', 'email', 'phone']

    @http.route('/booking', type='http', auth='public', website=True, sitemap=True)
    def booking_page(self, **kw):
        return request.render('it_support_management.website_booking_page', {
            'success': kw.get('success'),
            'error_fields': (kw.get('error_fields') or '').split(',') if kw.get('error_fields') else [],
            'formatted': kw,
        })

    @http.route('/booking/submit', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def booking_submit(self, **post):
        missing = [f for f in self.REQUIRED_FIELDS if not (post.get(f) or '').strip()]
        if missing:
            return request.redirect('/booking?%s' % url_encode({
                'error_fields': ','.join(missing),
                'name': post.get('name', ''),
                'company_name': post.get('company_name', ''),
                'email': post.get('email', ''),
                'phone': post.get('phone', ''),
                'preferred_datetime': post.get('preferred_datetime', ''),
                'message': post.get('message', ''),
            }))

        request.env['it.support.booking.request'].create({
            'name': post.get('name', '').strip(),
            'company_name': (post.get('company_name') or '').strip(),
            'email': post.get('email', '').strip(),
            'phone': post.get('phone', '').strip(),
            'preferred_datetime': (post.get('preferred_datetime') or '').strip(),
            'message': (post.get('message') or '').strip(),
        })

        return request.redirect('/booking?success=1')
