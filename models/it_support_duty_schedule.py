# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ItSupportDutySchedule(models.Model):
    _name = 'it.support.duty.schedule'
    _description = 'IT Support Duty Schedule'
    _order = 'date desc, start_time'
    _rec_name = 'display_name'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    start_time = fields.Float(
        string='Shift Start', required=True, default=8.0,
        help='Shift start time, in 24h float format (e.g. 8.5 = 8:30 AM, 13.0 = 1:00 PM).',
    )
    end_time = fields.Float(
        string='Shift End', required=True, default=17.0,
        help='Shift end time, in 24h float format (e.g. 17.5 = 5:30 PM).',
    )
    agent_id = fields.Many2one(
        'res.users', string='On-Duty Agent', required=True,
        domain=lambda self: [('group_ids', 'in', self.env.ref('it_support_management.group_it_support_agent').id)],
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True)

    _check_shift_order = models.Constraint(
        'CHECK(end_time > start_time)',
        'Shift end time must be after the start time.',
    )

    @api.depends('date', 'start_time', 'end_time', 'agent_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.date and rec.agent_id:
                rec.display_name = (
                    f"{rec.date} {rec._format_float_time(rec.start_time)}-"
                    f"{rec._format_float_time(rec.end_time)} : {rec.agent_id.name}"
                )
            else:
                rec.display_name = ''

    @staticmethod
    def _format_float_time(value):
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        return f"{hours:02d}:{minutes:02d}"

    @api.constrains('date', 'start_time', 'end_time', 'agent_id')
    def _check_no_overlap(self):
        for rec in self:
            overlapping = self.search([
                ('id', '!=', rec.id),
                ('date', '=', rec.date),
                ('agent_id', '=', rec.agent_id.id),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ])
            if overlapping:
                raise UserError(_(
                    'This agent already has an overlapping shift on %(date)s: %(shift)s.',
                    date=rec.date, shift=overlapping[0].display_name,
                ))

    @api.model
    def get_agent_on_duty(self, at_datetime=None):
        """Return the res.users currently on duty at the given moment (defaults to
        now), or an empty recordset if nobody is scheduled.

        NOTE on time zones: shift start_time/end_time are entered as plain hour-of-day
        floats (e.g. 8.0 = 8:00 AM) representing the company's local office hours, not
        UTC. This method compares them against the current wall-clock time using
        Python's local datetime.now() (the server's configured local time), which is
        the simplest approach that avoids relying on company/partner timezone fields
        that may differ between Odoo versions or company configurations. If the Odoo
        server is deployed in a different time zone than the office, this should be
        revisited to convert explicitly via pytz using the company's actual timezone.
        """
        from datetime import datetime
        moment = at_datetime or datetime.now()
        current_date = moment.date()
        current_hour_float = moment.hour + moment.minute / 60.0 + moment.second / 3600.0

        schedule = self.search([
            ('date', '=', current_date),
            ('start_time', '<=', current_hour_float),
            ('end_time', '>', current_hour_float),
        ], limit=1)
        return schedule.agent_id

    def action_open_calendar(self):
        return {
            'name': _('Duty Schedule'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.support.duty.schedule',
            'view_mode': 'calendar,list,form',
        }
