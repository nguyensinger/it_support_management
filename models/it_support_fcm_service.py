# -*- coding: utf-8 -*-
"""FCM V1 HTTP API helper.

Odoo gọi Firebase Cloud Messaging V1 API để gửi push notification đến
thiết bị Android của IT support agent khi:
  - Có ticket mới được tạo (dispatch notification cho agent on-duty)
  - Có tin nhắn chat mới từ khách hàng trên ticket đang xử lý

Authentication: FCM V1 dùng OAuth2 access token lấy từ Service Account JSON
(không dùng Server Key của legacy API đã bị deprecated từ 6/2024).

File service account JSON đặt tại:
  <odoo_module_dir>/firebase-service-account.json
Không commit file này lên git — thêm vào .gitignore.
"""
import json
import logging
import os
import time

import requests

_logger = logging.getLogger(__name__)

# Đường dẫn tới file service account JSON, đặt cùng thư mục với module
_SERVICE_ACCOUNT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'firebase-service-account.json',
)

# Cache access token để tránh gọi Google OAuth2 mỗi lần gửi notification
# Format: {'token': '...', 'expires_at': <unix timestamp>}
_token_cache = {}

FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'


def _load_service_account():
    """Đọc file service account JSON."""
    if not os.path.exists(_SERVICE_ACCOUNT_PATH):
        _logger.error(
            'FCM service account file not found: %s. '
            'Push notifications will not be sent.',
            _SERVICE_ACCOUNT_PATH,
        )
        return None
    try:
        with open(_SERVICE_ACCOUNT_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        _logger.error('Failed to load FCM service account: %s', e)
        return None


def _get_access_token():
    """Lấy OAuth2 access token từ Google, dùng cache nếu còn hạn."""
    global _token_cache
    now = time.time()
    if _token_cache.get('token') and _token_cache.get('expires_at', 0) > now + 60:
        return _token_cache['token']

    sa = _load_service_account()
    if not sa:
        return None

    try:
        import jwt  # PyJWT — thường đã có trong Odoo dependencies
    except ImportError:
        _logger.error('PyJWT not installed. Run: pip install PyJWT cryptography')
        return None

    try:
        now_int = int(now)
        payload = {
            'iss': sa['client_email'],
            'scope': FCM_SCOPE,
            'aud': GOOGLE_TOKEN_URL,
            'iat': now_int,
            'exp': now_int + 3600,
        }
        private_key = sa['private_key']
        assertion = jwt.encode(payload, private_key, algorithm='RS256')

        resp = requests.post(GOOGLE_TOKEN_URL, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data['access_token']
        expires_in = data.get('expires_in', 3600)
        _token_cache = {'token': token, 'expires_at': now + expires_in}
        return token
    except Exception as e:
        _logger.error('Failed to get FCM access token: %s', e)
        return None


def send_fcm_notification(fcm_tokens, title, body, data=None):
    """Gửi push notification đến danh sách FCM token.

    Args:
        fcm_tokens: list[str] — danh sách FCM token của thiết bị cần nhận
        title: str — tiêu đề notification
        body: str — nội dung notification
        data: dict — data payload tùy chọn (key-value string, để Flutter xử lý)

    Returns:
        dict {'sent': n, 'failed': n, 'invalid_tokens': [...]}
    """
    if not fcm_tokens:
        return {'sent': 0, 'failed': 0, 'invalid_tokens': []}

    sa = _load_service_account()
    if not sa:
        return {'sent': 0, 'failed': len(fcm_tokens), 'invalid_tokens': []}

    access_token = _get_access_token()
    if not access_token:
        return {'sent': 0, 'failed': len(fcm_tokens), 'invalid_tokens': []}

    project_id = sa.get('project_id')
    fcm_url = f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    sent = 0
    failed = 0
    invalid_tokens = []

    for token in fcm_tokens:
        message = {
            'message': {
                'token': token,
                'notification': {
                    'title': title,
                    'body': body,
                },
                'android': {
                    'priority': 'high',
                    'notification': {
                        'sound': 'default',
                        'channel_id': 'it_support_notifications',
                    },
                },
            }
        }
        if data:
            # FCM data payload — tất cả values phải là string
            message['message']['data'] = {k: str(v) for k, v in data.items()}

        try:
            resp = requests.post(fcm_url, json=message, headers=headers, timeout=10)
            if resp.status_code == 200:
                sent += 1
            else:
                failed += 1
                resp_data = resp.json() if resp.content else {}
                error = resp_data.get('error', {})
                # Token không còn hợp lệ (app uninstall, token expire...). FCM v1 API
                # đặt mã lỗi thực sự (UNREGISTERED/INVALID_ARGUMENT) trong
                # error.details[].errorCode - KHÔNG phải error.status (đó là mã lỗi
                # HTTP chung chung, ví dụ 'NOT_FOUND' cho cả token die lẫn lỗi khác).
                detail_codes = {
                    d.get('errorCode') for d in error.get('details', []) if d.get('errorCode')
                }
                if detail_codes & {'UNREGISTERED', 'INVALID_ARGUMENT'}:
                    invalid_tokens.append(token)
                _logger.warning(
                    'FCM send failed for token %s...: %s %s',
                    token[:20], resp.status_code, resp_data
                )
        except Exception as e:
            failed += 1
            _logger.error('FCM request error: %s', e)

    _logger.info('FCM: sent=%d failed=%d invalid=%d', sent, failed, len(invalid_tokens))
    return {'sent': sent, 'failed': failed, 'invalid_tokens': invalid_tokens}
