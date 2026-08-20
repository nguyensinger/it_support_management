# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import email_normalize

from .it_support_device_pairing_code import INVITE_CODE_VALIDITY_MINUTES


class ItSupportDeviceInviteWizard(models.TransientModel):
    _name = 'it.support.device.invite.wizard'
    _description = 'Invite End User to Set Up Desktop Client'

    customer_id = fields.Many2one(
        'res.partner', string='Company', required=True,
        domain="[('is_company', '=', True)]",
    )
    name = fields.Char(string='Full Name', required=True)
    email = fields.Char(string='Email', required=True)

    def action_send_invite(self):
        self.ensure_one()
        email = email_normalize(self.email or '')
        if not email:
            raise UserError(_('Please enter a valid email address.'))

        # Same find-or-create-by-email pattern as the portal self-service
        # invite (/my/team/invite) - and the same reason customer_id is passed
        # explicitly to create_for_partner rather than left to derive from the
        # invitee's own record: the email may already match an unrelated
        # existing partner (a different customer's contact, or a standalone
        # signup with no company), and the code must still be pinned to the
        # Company chosen here, not whatever that partner's record carries.
        Partner = self.env['res.partner'].sudo()
        invitee = Partner.search([('email', '=', email)], limit=1)
        if not invitee:
            invitee = Partner.create({'name': self.name, 'email': email, 'parent_id': self.customer_id.id})

        Pairing = self.env['it.support.device.pairing.code'].sudo()
        pairing = Pairing.create_for_partner(
            invitee, validity_minutes=INVITE_CODE_VALIDITY_MINUTES, customer=self.customer_id
        )

        template = self.env.ref('it_support_management.mail_template_device_invite').sudo()
        template.send_mail(pairing.id, force_send=True)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invitation sent'),
                'message': _('%s will receive an email with the download link, setup steps, and their pairing code.', self.email),
                'type': 'success',
            },
        }
