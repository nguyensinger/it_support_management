# -*- coding: utf-8 -*-
from odoo import fields, models


class ItSupportAgentDevice(models.Model):
    """Lưu FCM token của từng thiết bị (điện thoại) mà IT agent dùng để nhận
    push notification. Mỗi agent có thể có nhiều thiết bị (điện thoại cá nhân,
    máy tính bảng, v.v.) — mỗi bản ghi ứng với 1 cặp (agent, thiết bị).

    Token được gửi lên từ Flutter app mỗi khi app khởi động (token có thể
    thay đổi khi app reinstall hoặc FCM refresh), nên dùng upsert theo
    (agent_id, device_id) thay vì tạo bản ghi mới mỗi lần.
    """
    _name = 'it.support.agent.device'
    _description = 'IT Support Agent FCM Device Token'
    _order = 'write_date desc'

    agent_id = fields.Many2one(
        'res.users', string='Agent', required=True, ondelete='cascade', index=True,
    )
    # device_fingerprint: chuỗi định danh thiết bị do Flutter app tạo ra
    # (ví dụ: Android ID hoặc UUID lưu trong SharedPreferences lần đầu khởi động).
    # Dùng để upsert — tìm đúng bản ghi của thiết bị này và cập nhật token mới,
    # không tạo duplicate khi token FCM refresh.
    device_fingerprint = fields.Char(string='Device Fingerprint', required=True, index=True)
    fcm_token = fields.Char(string='FCM Token', required=True)
    last_seen = fields.Datetime(string='Last Seen', default=fields.Datetime.now)

    _sql_constraints = [
        ('unique_agent_device', 'UNIQUE(agent_id, device_fingerprint)',
         'Each device can only have one FCM token per agent.'),
    ]
