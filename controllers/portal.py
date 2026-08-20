# -*- coding: utf-8 -*-
from markupsafe import Markup
from werkzeug.urls import url_encode

from odoo import http, fields, _
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

    @http.route(['/my/device-pairing'], type='http', auth='user', website=True)
    def portal_device_pairing(self, **kw):
        values = self._prepare_portal_layout_values()
        Pairing = request.env['it.support.device.pairing.code'].sudo()
        pairing = Pairing.search([
            ('partner_id', '=', request.env.user.partner_id.id),
            ('used', '=', False),
        ], order='create_date desc', limit=1)
        # Drop it silently once expired - the template just goes back to
        # showing the "Generate" button, no need to surface an error state.
        if pairing and pairing.expires_at < fields.Datetime.now():
            pairing = Pairing

        values.update({
            'page_name': 'device_pairing',
            'pairing': pairing,
        })
        return request.render('it_support_management.portal_device_pairing', values)

    @http.route(['/my/device-pairing/generate'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_device_pairing_generate(self, **post):
        request.env['it.support.device.pairing.code'].sudo().create_for_partner(request.env.user.partner_id)
        return request.redirect('/my/device-pairing')

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
        customer = request.env.user.partner_id.commercial_partner_id
        is_company = customer.is_company

        devices = request.env['it.customer.device']
        existing_end_user = request.env['it.support.end.user']
        if is_company:
            devices = devices.sudo().search([('customer_id', '=', customer.id)], order='name')
            partner_email = request.env.user.partner_id.email
            if partner_email:
                existing_end_user = existing_end_user.sudo().search(
                    [('customer_id', '=', customer.id), ('email', '=', partner_email)], limit=1
                )

        values.update({
            'page_name': 'ticket',
            'error': kw.get('error'),
            'formatted': dict(kw),
            'is_company': is_company,
            'devices': devices,
            'existing_department': existing_end_user.department or '',
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
        partner = request.env.user.partner_id
        customer = partner.commercial_partner_id

        end_user = request.env['it.support.end.user']
        device = request.env['it.customer.device']
        if customer.is_company:
            # Who's actually asking, and from which machine - without this a
            # ticket from a company customer just says "the company", which
            # isn't enough for an agent to know who to call or what to remote
            # into. Match/update the requester's own end-user record (by
            # email, under this customer) rather than trusting a free-typed
            # name that could collide with someone else's existing record.
            EndUser = request.env['it.support.end.user'].sudo()
            department = (post.get('department') or '').strip()
            if partner.email:
                end_user = EndUser.search(
                    [('customer_id', '=', customer.id), ('email', '=', partner.email)], limit=1
                )
            if end_user:
                if department and department != end_user.department:
                    end_user.write({'department': department})
            else:
                end_user = EndUser.create({
                    'name': partner.name,
                    'email': partner.email,
                    'phone': partner.phone,
                    'department': department,
                    'customer_id': customer.id,
                })

            device_id = post.get('device_id')
            device_name = (post.get('device_name') or '').strip()
            Device = request.env['it.customer.device'].sudo()
            if device_id:
                try:
                    device = Device.browse(int(device_id)).exists().filtered(lambda d: d.customer_id == customer)
                except ValueError:
                    device = Device
            elif device_name:
                device = Device.search([('customer_id', '=', customer.id), ('name', '=', device_name)], limit=1)
                if not device:
                    device = Device.create({'name': device_name, 'customer_id': customer.id, 'user_id': end_user.id})
                elif not device.user_id:
                    device.write({'user_id': end_user.id})

        ticket = request.env['it.support.ticket'].sudo().create({
            'customer_id': customer.id,
            'subject': subject,
            'description': Markup('<p>%s</p>') % description if description else False,
            'priority': priority,
            'end_user_id': end_user.id if end_user else False,
            'device_id': device.id if device else False,
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
