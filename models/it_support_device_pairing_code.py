# -*- coding: utf-8 -*-
import random
import string
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

CODE_LENGTH = 6
CODE_VALIDITY_MINUTES = 15
# A code emailed to an invited team member has to survive them getting to it
# whenever they actually sit down to install the client - not the same
# "do it right now" assumption as the self-service /my/device-pairing page.
INVITE_CODE_VALIDITY_MINUTES = 60 * 24 * 7
# Ambiguous-looking characters (0/O, 1/I/L) dropped - this gets typed by hand
# into the Desktop Client, same reasoning as Wi-Fi/device pairing codes elsewhere.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


class ItSupportDevicePairingCode(models.Model):
    _name = 'it.support.device.pairing.code'
    _description = 'Desktop Client Pairing Code'
    _order = 'create_date desc'

    code = fields.Char(required=True, copy=False, index=True)
    # The logged-in portal user who generated the code - kept separate from
    # customer_id because the requester may be a person contact under a
    # company (customer_id resolves to the commercial partner, matching how
    # tickets/end-users are scoped elsewhere in this module).
    partner_id = fields.Many2one('res.partner', string='Requested By', required=True, ondelete='cascade')
    customer_id = fields.Many2one('res.partner', string='Customer', required=True)
    expires_at = fields.Datetime(required=True)
    used = fields.Boolean(default=False)
    device_id = fields.Many2one('it.customer.device', string='Paired Device', readonly=True)

    _code_unique = models.Constraint('unique(code)', 'Pairing code collision - please try again.')

    @api.model
    def _generate_code(self):
        for _attempt in range(20):
            code = ''.join(random.choices(CODE_ALPHABET, k=CODE_LENGTH))
            if not self.search_count([('code', '=', code)]):
                return code
        raise UserError(_('Could not generate a unique pairing code, please try again.'))

    @api.model
    def create_for_partner(self, partner, validity_minutes=CODE_VALIDITY_MINUTES):
        """One active code per requester/invitee at a time - generating a new one
        silently invalidates any earlier unused code instead of letting several
        pile up."""
        self.search([('partner_id', '=', partner.id), ('used', '=', False)]).write({'used': True})
        return self.create({
            'code': self._generate_code(),
            'partner_id': partner.id,
            'customer_id': partner.commercial_partner_id.id,
            'expires_at': fields.Datetime.now() + timedelta(minutes=validity_minutes),
        })

    def _check_valid(self):
        self.ensure_one()
        if self.used:
            raise UserError(_('This pairing code has already been used. Generate a new one from your account.'))
        if self.expires_at < fields.Datetime.now():
            raise UserError(_('This pairing code has expired. Generate a new one from your account.'))
