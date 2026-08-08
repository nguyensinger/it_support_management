# -*- coding: utf-8 -*-
from odoo import models


class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    def _get_payment_method_information(self):
        # Common manual payment methods used by small businesses in Canada, beyond the
        # generic "Manual Payment" Odoo ships with. 'mode': 'multi' + a journal 'type'
        # here is what makes creating the account.payment.method record below
        # automatically attach it (as an account.payment.method.line) to every matching
        # journal, in every company - see AccountPaymentMethod.create()/
        # _auto_link_payment_methods() in the account module.
        res = super()._get_payment_method_information()
        res.update({
            'it_support_etransfer': {'mode': 'multi', 'type': ('bank',)},
            'it_support_eft': {'mode': 'multi', 'type': ('bank',)},
            'it_support_cheque': {'mode': 'multi', 'type': ('bank',)},
            'it_support_cash': {'mode': 'multi', 'type': ('cash',)},
            'it_support_credit_card': {'mode': 'multi', 'type': ('bank',)},
            'it_support_wire_transfer': {'mode': 'multi', 'type': ('bank',)},
        })
        return res
