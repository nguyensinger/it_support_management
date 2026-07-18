# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import AccessDenied
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _auth_method_it_support_api_key(cls):
        """Dedicated authentication method for the IT Support REST API.
        The desktop agent / mobile app send the header:
            Authorization: Bearer <api_key>
        The API key is created via Settings > Technical > API Keys (res.users.apikeys),
        assigned to a technical user (e.g. an 'it-agent-bot' user for the desktop agent,
        or the IT support agent's own user when logged in from the mobile app).
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.lower().startswith('bearer '):
            raise AccessDenied(_('Missing or malformed Authorization header: Bearer <api_key>'))
        api_key = auth_header.split(' ', 1)[1].strip()
        if not api_key:
            raise AccessDenied(_('Empty API key.'))

        uid = request.env['res.users.apikeys'].sudo()._check_credentials(
            scope='rpc', key=api_key
        )
        if not uid:
            raise AccessDenied(_('Invalid or expired API key.'))
        request.update_env(user=uid)
