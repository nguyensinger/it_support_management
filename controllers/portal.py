# -*- coding: utf-8 -*-
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
