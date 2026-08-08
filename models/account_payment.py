# -*- coding: utf-8 -*-
from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _get_method_codes_using_bank_account(self):
        # Odoo only shows "Recipient Bank Account" on the Pay wizard for the built-in
        # 'manual' method by default. Our new bank-transfer-style methods (EFT, e-Transfer,
        # cheque once deposited, wire, card settlement) all land in one of the company's
        # own bank accounts too, so they should offer the same field. Cash is excluded -
        # it never lands in a bank account.
        return super()._get_method_codes_using_bank_account() + [
            'it_support_etransfer',
            'it_support_eft',
            'it_support_cheque',
            'it_support_credit_card',
            'it_support_wire_transfer',
        ]
