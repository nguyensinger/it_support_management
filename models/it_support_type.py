# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models


class ItSupportType(models.Model):
    _name = 'it.support.type'
    _description = 'IT Support Type (Onsite/Online) - Pricing & Block Rules'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    mode = fields.Selection([
        ('onsite', 'Onsite'),
        ('online', 'Online'),
    ], string='Mode', required=True, default='online')
    sequence = fields.Integer(default=10)

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    price_per_hour = fields.Monetary(string='Price per Hour', required=True, currency_field='currency_id')

    first_block_minutes = fields.Integer(
        string='First Block (minutes)', default=15, required=True,
        help='Size of the FIRST billing block, in minutes. Any amount of time worked up '
             'to this value is billed as this full block. '
             'Example (Onsite): set to 60 so any session up to 1 hour is billed as a full hour.'
    )
    block_minutes = fields.Integer(
        string='Subsequent Block (minutes)', default=15, required=True,
        help='Size of each billing block AFTER the first block, in minutes. Time worked '
             'beyond the first block is rounded up to this block size. '
             'Example (Onsite): set to 15 so time beyond the first hour is billed in 15-minute increments. '
             'Example (Online): set equal to First Block so the whole duration is billed uniformly.'
    )
    min_charge_blocks = fields.Integer(
        string='Minimum Blocks per Session', default=1, required=True,
        help='Minimum number of billable blocks (counting the first block as 1) charged '
             'per session, even if actual time worked is less.'
    )

    description = fields.Text(string='Terms / Notes')
    active = fields.Boolean(default=True)

    _first_block_minutes_positive = models.Constraint(
        'CHECK(first_block_minutes > 0)',
        'The first billing block must be greater than 0.',
    )
    _block_minutes_positive = models.Constraint(
        'CHECK(block_minutes > 0)',
        'The subsequent billing block must be greater than 0.',
    )
    _min_block_positive = models.Constraint(
        'CHECK(min_charge_blocks > 0)',
        'The minimum number of blocks must be greater than 0.',
    )
    _price_non_negative = models.Constraint(
        'CHECK(price_per_hour >= 0)',
        'The price cannot be negative.',
    )

    def compute_billable_hours(self, duration_hours):
        """Compute the number of billable hours according to this support type's
        two-tier block rules:
          - Any time up to `first_block_minutes` is billed as one full first block.
          - Time beyond that is rounded up to the next `block_minutes` increment.
          - The result is never less than `min_charge_blocks` x first block size.

        Example (Onsite, first_block=60min, block=15min): 1h12m worked ->
          first block = 1h, remainder = 12min -> rounds up to 1 block of 15min -> total 1.25h.

        Example (Online, first_block=15min, block=15min, i.e. uniform): 22min worked ->
          remainder after a 0-length "first block" rounds up normally to 0.5h (2 blocks of 15min).
          (With first_block == block_minutes, this degenerates to simple uniform rounding.)

        duration_hours: actual hours worked (float)
        return: billable hours (float)
        """
        self.ensure_one()
        if duration_hours <= 0:
            return 0.0

        first_block_hours = self.first_block_minutes / 60.0
        block_hours = self.block_minutes / 60.0

        if duration_hours <= first_block_hours:
            billable_hours = first_block_hours
        else:
            remainder_hours = duration_hours - first_block_hours
            extra_blocks = math.ceil(remainder_hours / block_hours)
            billable_hours = first_block_hours + extra_blocks * block_hours

        min_hours = self.min_charge_blocks * first_block_hours
        return max(billable_hours, min_hours)

    def compute_amount(self, duration_hours):
        self.ensure_one()
        billable_hours = self.compute_billable_hours(duration_hours)
        return billable_hours * self.price_per_hour
