# -*- coding: utf-8 -*-
from odoo import fields, models


class ItSupportBookingRequest(models.Model):
    _name = 'it.support.booking.request'
    _description = 'Website Booking Request (pending customer approval)'
    _order = 'create_date desc'

    name = fields.Char(string='Full Name', required=True)
    company_name = fields.Char(string='Company')
    email = fields.Char(string='Email', required=True)
    phone = fields.Char(string='Phone', required=True)
    # Ô text tự do - khách tự gõ ngày giờ mong muốn, KHÔNG dùng date/time picker
    # thật (đơn giản hoá theo yêu cầu, vì không dùng app Appointments Enterprise).
    preferred_datetime = fields.Char(string='Preferred Date/Time')
    message = fields.Text(string='Message / What do you need help with?')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True)
    partner_id = fields.Many2one('res.partner', string='Created Customer', readonly=True)

    def action_confirm(self):
        """Duyệt yêu cầu: tìm Customer đã có (khớp theo email) hoặc tạo mới,
        gắn vào request, chuyển trạng thái sang Confirmed."""
        for rec in self:
            if rec.state != 'pending':
                continue
            partner = self.env['res.partner'].sudo().search([('email', '=', rec.email)], limit=1)
            if not partner:
                partner = self.env['res.partner'].sudo().create({
                    'name': rec.company_name or rec.name,
                    'is_company': bool(rec.company_name),
                    'email': rec.email,
                    'phone': rec.phone,
                })
            rec.write({'state': 'confirmed', 'partner_id': partner.id})
        return True

    def action_reject(self):
        for rec in self:
            if rec.state == 'pending':
                rec.write({'state': 'rejected'})
        return True
