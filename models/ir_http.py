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
        Two kinds of key are accepted:
        1. A real Odoo API key (Settings > Technical > API Keys, res.users.apikeys),
           assigned to a technical user - used by the mobile app (the agent's own
           user) and any manually-provisioned desktop install.
        2. A per-device key minted automatically at /api/v1/device/pair and stored
           on it.customer.device.agent_api_key - this is what a Desktop Client set
           up via a pairing code uses, so the end user never has to know or type
           any API key themselves. Resolves to the public user: every endpoint
           already does its own sudo()'d model access, so this is just enough
           identity for env/session plumbing to work, not a source of privilege.
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
        if uid:
            request.update_env(user=uid)
            return

        device = request.env['it.customer.device'].sudo().search([('agent_api_key', '=', api_key)], limit=1)
        if device:
            request.update_env(user=request.env.ref('base.public_user').id)
            return

        raise AccessDenied(_('Invalid or expired API key.'))
