# -*- coding: utf-8 -*-
from markupsafe import Markup
from werkzeug.urls import url_encode

from odoo import http, _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class ItSupportCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            Ticket = request.env['it.support.ticket']
            values['ticket_count'] = Ticket.search_count([]) if Ticket.has_access('read') else 0
        return values

    def _get_ticket_searchbar_sortings(self):
        return {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_tickets(self, page=1, sortby=None, **kw):
        values = self._prepare_portal_layout_values()
        Ticket = request.env['it.support.ticket']

        searchbar_sortings = self._get_ticket_searchbar_sortings()
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        domain = []
        ticket_count = Ticket.search_count(domain)
        pager = portal_pager(
            url='/my/tickets',
            url_args={'sortby': sortby},
            total=ticket_count,
            page=page,
            step=self._items_per_page,
        )
        tickets = Ticket.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_tickets_history'] = tickets.ids[:100]

        values.update({
            'tickets': tickets,
            'page_name': 'ticket',
            'pager': pager,
            'default_url': '/my/tickets',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
        })
        return request.render('it_support_management.portal_my_tickets', values)

    @http.route(['/my/tickets/new'], type='http', auth='user', website=True)
    def portal_new_ticket_form(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'ticket',
            'error': kw.get('error'),
            'formatted': dict(kw),
        })
        return request.render('it_support_management.portal_new_ticket', values)

    @http.route(['/my/tickets/new/submit'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_new_ticket_submit(self, **post):
        subject = (post.get('subject') or '').strip()
        if not subject:
            return request.redirect('/my/tickets/new?%s' % url_encode({
                'error': 'subject',
                'description': post.get('description', ''),
                'priority': post.get('priority', ''),
            }))

        priority = post.get('priority') if post.get('priority') in ('0', '1', '2', '3') else '1'
        description = (post.get('description') or '').strip()

        # customer_id is derived from the logged-in user, never taken from client
        # input - a portal user must not be able to create a ticket under a
        # different customer's name just by tampering with a form field.
        customer = request.env.user.partner_id.commercial_partner_id
        ticket = request.env['it.support.ticket'].sudo().create({
            'customer_id': customer.id,
            'subject': subject,
            'description': Markup('<p>%s</p>') % description if description else False,
            'priority': priority,
        })

        # Cap at 10 files / 10MB each - generous for photos/screenshots, not
        # meant as a real abuse guard (auth='user' already limits this to
        # logged-in portal customers).
        MAX_ATTACHMENTS = 10
        MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
        attachments = []
        for file in request.httprequest.files.getlist('attachments')[:MAX_ATTACHMENTS]:
            if not file or not file.filename:
                continue
            data = file.read()
            if data and len(data) <= MAX_ATTACHMENT_SIZE:
                attachments.append((file.filename, data))

        if attachments:
            ticket.sudo().message_post(
                body=Markup('<p>Attachment(s) from customer</p>'),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                attachments=attachments,
            )

        return request.redirect('/my/tickets/%s' % ticket.id)

    @http.route(['/my/tickets/<int:ticket_id>'], type='http', auth='user', website=True)
    def portal_my_ticket(self, ticket_id, access_token=None, **kw):
        try:
            ticket_sudo = self._document_check_access('it.support.ticket', ticket_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._get_page_view_values(
            ticket_sudo, access_token, {'page_name': 'ticket'}, 'my_tickets_history', False, **kw
        )
        values['ticket'] = ticket_sudo
        values['messages'] = ticket_sudo.message_ids.filtered(
            lambda m: m.message_type == 'comment'
        ).sorted('date')
        return request.render('it_support_management.portal_my_ticket', values)
