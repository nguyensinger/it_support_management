# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    # Canadian EFT/direct-deposit accounts are identified by 3 numbers, not 1:
    # a 3-digit Institution Number, a 5-digit Transit (branch) Number, and the
    # Account Number itself. Odoo's generic model only has Account Number, plus
    # a free "Clearing Number" field - reused here as Institution Number (same
    # pattern l10n_us uses for ABA/Routing) with a new field added for Transit.
    l10n_ca_transit_number = fields.Char(string='Transit Number')
    show_l10n_ca_transit = fields.Boolean(compute='_compute_show_l10n_ca_transit')

    @api.depends('country_code', 'acc_type')
    def _compute_show_l10n_ca_transit(self):
        for bank in self:
            bank.show_l10n_ca_transit = bank.country_code == 'CA' and bank.acc_type != 'iban'

    @api.constrains('l10n_ca_transit_number')
    def _check_l10n_ca_transit_number(self):
        for bank in self:
            if bank.country_code == 'CA' and bank.l10n_ca_transit_number and not re.match(r'^\d{5}$', bank.l10n_ca_transit_number):
                raise ValidationError(_('Transit Number must be exactly 5 digits.'))

    @api.constrains('clearing_number')
    def _check_l10n_ca_institution_number(self):
        for bank in self:
            if bank.country_code == 'CA' and bank.clearing_number and not re.match(r'^\d{3}$', bank.clearing_number):
                raise ValidationError(_('Institution Number must be exactly 3 digits.'))
