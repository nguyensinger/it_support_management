# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup
from werkzeug.urls import url_encode

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)


class ItSupportWebsiteSignup(http.Controller):
    """Public self-service "Sign Up" page: lets a customer open their own portal
    account instead of waiting for staff to click "Grant Portal Access".

    Its own form (not Odoo's stock /web/signup) so it can collect the same
    Person/Company + address info the Booking form does - VM Tech needs that
    for support/invoicing regardless of how the contact was created. No
    password is collected here: exactly like the staff-initiated Grant Portal
    Access flow, the customer sets their own password by clicking the link in
    the email that follows. That proves they actually own the inbox - typing a
    known customer's email into this form alone must not grant access to that
    customer's existing tickets/invoices.
    """

    REQUIRED_FIELDS = ['name', 'email', 'phone', 'street', 'city', 'state_id', 'zip']
    RECAPTCHA_ACTION = 'signup_account'

    @http.route('/signup-account', type='http', auth='public', website=True, sitemap=True)
    def signup_account_page(self, **kw):
        if not request.env.user._is_public():
            return request.redirect('/my')

        return request.render('it_support_management.website_signup_page', {
            'success': kw.get('success'),
            'error_fields': (kw.get('error_fields') or '').split(',') if kw.get('error_fields') else [],
            'formatted': dict(kw),
            'provinces': request.env['res.country.state'].sudo().search(
                [('country_id', '=', request.env.ref('base.ca').id)], order='name'
            ),
        })

    @http.route('/signup-account/submit', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def signup_account_submit(self, **post):
        company_type = post.get('company_type') if post.get('company_type') in ('person', 'company') else 'person'

        def redirect_with_error(error_fields):
            return request.redirect('/signup-account?%s' % url_encode({
                'error_fields': ','.join(error_fields),
                'name': post.get('name', ''),
                'company_name': post.get('company_name', ''),
                'email': post.get('email', ''),
                'phone': post.get('phone', ''),
                'street': post.get('street', ''),
                'city': post.get('city', ''),
                'state_id': post.get('state_id', ''),
                'zip': post.get('zip', ''),
                'company_type': company_type,
            }))

        try:
            request.env['ir.http']._verify_request_recaptcha_token(self.RECAPTCHA_ACTION)
        except (UserError, ValidationError):
            return redirect_with_error(['captcha'])

        missing = [f for f in self.REQUIRED_FIELDS if not (post.get(f) or '').strip()]

        email = email_normalize(post.get('email', '').strip()) if post.get('email') else False
        if not email and 'email' not in missing:
            missing.append('email')

        state_id = False
        if 'state_id' not in missing:
            # confirm it's actually one of the offered Canadian provinces (defends
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

        if missing:
            return redirect_with_error(missing)

        Partner = request.env['res.partner'].sudo()
        # Match on the SIGNER's own email only (never company name/phone - too
        # ambiguous, risks attaching a stranger to an existing customer's data).
        signer_partner = Partner.search([('email', '=', email)], limit=1)

        if not signer_partner:
            vals = {
                'name': post.get('name', '').strip(),
                'email': email,
                'phone': post.get('phone', '').strip(),
                'street': post.get('street', '').strip(),
                'city': post.get('city', '').strip(),
                'state_id': state_id.id,
                'zip': post.get('zip', '').strip(),
                'country_id': state_id.country_id.id,
            }
            company_name = (post.get('company_name') or '').strip()
            if company_type == 'company' and company_name:
                # Real customer data pattern here is company + a person contact
                # under it (see e.g. Finnish Canadian Rest Home Association /
                # Bryan Nguyen) - the portal login belongs to the person, whose
                # commercial_partner_id resolves up to the company for the
                # ticket/invoice visibility record rules.
                company_partner = Partner.create({
                    'name': company_name,
                    'is_company': True,
                    'street': vals['street'],
                    'city': vals['city'],
                    'state_id': vals['state_id'],
                    'zip': vals['zip'],
                    'country_id': vals['country_id'],
                    'phone': vals['phone'],
                })
                vals['parent_id'] = company_partner.id
            signer_partner = Partner.create(vals)

        existing_user = signer_partner.user_ids[:1]
        if existing_user and existing_user._is_internal():
            # Matches a VM Tech staff account - not a customer self-signup case.
            return redirect_with_error(['staff_email'])

        try:
            if existing_user:
                user = existing_user
            else:
                user = request.env['res.users'].sudo().with_context(no_reset_password=True)._create_user_from_template({
                    'email': email,
                    'login': email,
                    'partner_id': signer_partner.id,
                    'company_id': request.env.company.id,
                    'company_ids': [(6, 0, request.env.company.ids)],
                })
        except Exception:
            _logger.exception('Self-signup: failed to create portal user for %s', email)
            return redirect_with_error(['general'])

        signer_partner.signup_prepare()

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        welcome_message = Markup(
            '<br/><br/>'
            'One more thing: install the <b>VM TECH Support Client</b> on your computer so you '
            'can open support tickets and chat with our team directly from your desktop - '
            '<a href="%s/download">download it here</a>. After installing, just open it and sign '
            'in with this same email once you\'ve activated your account above.'
        ) % base_url

        template = request.env.ref('auth_signup.portal_set_password_email')
        template.with_context(welcome_message=welcome_message).send_mail(user.id, force_send=True)

        return request.redirect('/signup-account?success=1')
