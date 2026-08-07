# -*- coding: utf-8 -*-
import logging
import time

from odoo import http, fields
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)

POLL_WAIT_SECONDS = 25
POLL_CHECK_INTERVAL_SECONDS = 1.5


def _json_error(message, status=400):
    """With type='jsonrpc' routes, the Odoo dispatcher AUTOMATICALLY wraps the method's
    return value into {jsonrpc: "2.0", id: ..., result: <return value>}. So the method
    only needs to return a plain dict directly, WITHOUT wrapping it again in
    {'result': ...} (doing so would double-nest the result), and must never use
    request.make_json_response() here - that's the API for regular type='http' routes,
    which returns a full Response object; using it by mistake in type='jsonrpc' makes
    Odoo serialize it incorrectly as a string description of the object instead of
    actual JSON data.

    status no longer has real HTTP meaning here (always returns HTTP 200, business
    errors live in the JSON content) - kept as a parameter so existing calls don't need
    to change, but it is not used.
    """
    return {'error': message}


def _json_ok(data):
    return data if data is not None else {}


class ItSupportApiController(http.Controller):
    """
    REST API for:
      - Desktop Agent (installed on the customer's machine): device registration,
        heartbeat, ticket creation, chat.
      - Mobile App (IT support agent, Android/iOS): ticket list, ticket pickup,
        start/end session, chat.

    Authentication: "Authorization: Bearer <api_key>" header.
    The API key is created under Settings > Technical > API Keys, tied to a
    technical user.
    """

    # ---------------------------------------------------------------
    # DESKTOP AGENT ENDPOINTS
    # ---------------------------------------------------------------

    @http.route('/api/v1/device/register', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def device_register(self, **kw):
        """Called by the desktop agent on first install to register the device.
        Expected payload:
        {
          "customer_id": 12,                 # res.partner id (customer) - or use a
                                              # customer_code if available
          "hostname": "PC-ACCOUNTING-01",
          "serial_number": "SN12345",
          "os_info": "Windows 11 Pro",
          "cpu_info": "Intel i5-12400",
          "ram_gb": 16,
          "disk_info": "512GB SSD",
          "mac_address": "00:1A:2B:3C:4D:5E",
          "ip_address": "192.168.1.50",
          "ultraview_id": "987654321",
          "end_user_name": "John Smith",     # optional, creates an end_user if missing
          "end_user_email": "j.smith@customer.com",
          "end_user_phone": "778 288 3053",  # optional
          "end_user_department": "Accounting"  # optional
        }
        """
        Device = request.env['it.customer.device'].sudo()
        EndUser = request.env['it.support.end.user'].sudo()

        customer_id = kw.get('customer_id')
        if not customer_id:
            return _json_error('Missing customer_id.')
        customer = request.env['res.partner'].sudo().browse(customer_id)
        if not customer.exists():
            return _json_error('Customer not found.', status=404)

        end_user = False
        if kw.get('end_user_email'):
            end_user = EndUser.search([
                ('customer_id', '=', customer.id),
                ('email', '=', kw.get('end_user_email')),
            ], limit=1)
            # phone/department were previously accepted from the client but silently
            # dropped here - kept as separate fields (not folded into `vals` above)
            # since only non-empty ones should overwrite what's already on file.
            end_user_updates = {
                k: v for k, v in {
                    'name': kw.get('end_user_name'),
                    'phone': kw.get('end_user_phone'),
                    'department': kw.get('end_user_department'),
                }.items() if v
            }
            if not end_user and kw.get('end_user_name'):
                end_user = EndUser.create({
                    **end_user_updates,
                    'email': kw.get('end_user_email'),
                    'customer_id': customer.id,
                })
            elif end_user and end_user_updates:
                end_user.write(end_user_updates)

        device = Device.search([
            ('customer_id', '=', customer.id),
            ('name', '=', kw.get('hostname')),
        ], limit=1)

        vals = {
            'name': kw.get('hostname'),
            'customer_id': customer.id,
            'serial_number': kw.get('serial_number'),
            'os_info': kw.get('os_info'),
            'cpu_info': kw.get('cpu_info'),
            'ram_gb': kw.get('ram_gb', 0),
            'disk_info': kw.get('disk_info'),
            'mac_address': kw.get('mac_address'),
            'ip_address': kw.get('ip_address'),
            'ultraview_id': kw.get('ultraview_id'),
            'last_seen': fields.Datetime.now(),
        }
        if end_user:
            vals['user_id'] = end_user.id

        if device:
            device.write(vals)
        else:
            device = Device.create(vals)

        return _json_ok({
            'device_id': device.id,
            'device_name': device.name,
            'state': device.state,
        })

    @http.route('/api/v1/device/<int:device_id>/heartbeat', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def device_heartbeat(self, device_id, **kw):
        """Called periodically by the desktop agent (e.g. every 2-3 minutes) to report
        being alive and update any changed information."""
        device = request.env['it.customer.device'].sudo().browse(device_id)
        if not device.exists():
            return _json_error('Device not found.', status=404)
        device.heartbeat(vals=kw)
        return _json_ok({'device_id': device.id, 'last_seen': str(device.last_seen)})

    @http.route('/api/v1/ticket/create', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def ticket_create(self, **kw):
        """Called by the desktop agent when the user creates a support request from
        the app.
        Payload:
        {
          "device_id": 5,
          "subject": "Printer not working",
          "description": "Detailed description...",
          "priority": "1"
        }

        NOTE: the end user does NOT choose Online/Onsite when creating a ticket - that
        decision belongs to IT support after assessing the request (setting
        support_type_id on the ticket while handling it, or choosing support_mode
        directly when starting a session from the mobile app).
        """
        Ticket = request.env['it.support.ticket'].sudo()
        Device = request.env['it.customer.device'].sudo()

        device_id = kw.get('device_id')
        device = Device.browse(device_id) if device_id else Device
        if device_id and not device.exists():
            return _json_error('Device not found.', status=404)

        subject = kw.get('subject')
        if not subject:
            return _json_error('Missing subject.')

        vals = {
            'subject': subject,
            'description': kw.get('description'),
            'priority': kw.get('priority', '1'),
        }
        if device:
            vals['device_id'] = device.id
            vals['customer_id'] = device.customer_id.id
            if device.user_id:
                vals['end_user_id'] = device.user_id.id
        elif kw.get('customer_id'):
            vals['customer_id'] = kw.get('customer_id')
        else:
            return _json_error('Missing device_id or customer_id.')

        ticket = Ticket.create(vals)
        ticket._post_desktop_client_greeting()
        return _json_ok({
            'ticket_id': ticket.id,
            'ticket_name': ticket.name,
            'state': ticket.state,
        })

    @http.route('/api/v1/device/<int:device_id>/tickets', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def device_ticket_list(self, device_id, **kw):
        """Called by the desktop agent to get every ticket created from this device
        (including completed/cancelled ones) - used to populate the ticket dropdown
        on the Chat tab, letting the user review the history of older requests, not
        just the most recent one.
        """
        device = request.env['it.customer.device'].sudo().browse(device_id)
        if not device.exists():
            return _json_error('Device not found.', status=404)

        tickets = request.env['it.support.ticket'].sudo().search(
            [('device_id', '=', device_id)], order='create_date desc'
        )
        return _json_ok([{
            'id': t.id,
            'name': t.name,
            'subject': t.subject,
            'state': t.state,
        } for t in tickets])

    @http.route('/api/v1/ticket/<int:ticket_id>/message', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_post_message(self, ticket_id, **kw):
        """Send a chat message on a ticket (used by both the desktop agent and the
        mobile app). Leverages Odoo's built-in mail.thread (message_post), which
        automatically shows up in the chatter.
        Payload: {
            "body": "Chat content",
            "from_customer": true   # true if sent from the desktop agent (customer) ->
                                     # sends an email notification to the assigned IT
                                     # support agent. false/omit if sent from the
                                     # mobile app (the agent themselves).
        }
        """
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        body = kw.get('body')
        if not body:
            return _json_error('Missing body content.')

        if kw.get('from_customer'):
            # Message from the customer (desktop agent) - notify IT support by email
            ticket._notify_agents_new_customer_message(body)
        else:
            # Message from the IT support agent (mobile app) - no need to notify them
            ticket.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        message = ticket.message_ids.sorted('date', reverse=True)[:1]
        return _json_ok({'message_id': message.id, 'ticket_id': ticket.id})

    @http.route('/api/v1/ticket/<int:ticket_id>/messages', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_get_messages(self, ticket_id, **kw):
        """Get the chat history of a ticket (to display on the desktop agent / mobile app)."""
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        messages = ticket.message_ids.filtered(lambda m: m.message_type == 'comment').sorted('date')
        result = []
        for m in messages:
            author_name = m.author_id.name or m.email_from or 'IT Support'
            # Nếu tin nhắn này có author_id = customer_id của ticket (tức là gửi từ
            # Desktop Client App của khách hàng, xem _notify_agents_new_customer_message),
            # ghép thêm tên end_user (nhân sự cụ thể, vd "Karoliina") để agent biết chính
            # xác ai đang chat, không chỉ biết tên công ty.
            if ticket.end_user_id and m.author_id and m.author_id.id == ticket.customer_id.id:
                author_name = f'{ticket.end_user_id.name} ({author_name})'
            result.append({
                'id': m.id,
                'author': author_name,
                'body': m.body,
                'date': str(m.date),
            })
        return _json_ok(result)

    @http.route('/api/v1/ticket/<int:ticket_id>/realtime_channel', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_realtime_channel(self, ticket_id, **kw):
        """Return the channel name for the client (desktop agent / mobile app) to
        subscribe to via bus.bus and receive realtime updates (new chat, status
        change, session start/end) through Odoo's standard endpoint: /websocket (WS)
        or /longpolling/poll (HTTP long-polling fallback).
        """
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        return _json_ok({
            'channel': ticket._get_ticket_channel(),
            'websocket_url': '/websocket',
            'longpolling_url': '/longpolling/poll',
        })

    @http.route('/api/v1/dispatch_channel', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def dispatch_channel(self, **kw):
        """Shared channel for all on-duty agents' mobile apps to subscribe to and be
        notified of newly created tickets (especially unassigned ones)."""
        return _json_ok({
            'channel': request.env['it.support.ticket'].sudo()._get_dispatch_channel(),
            'websocket_url': '/websocket',
            'longpolling_url': '/longpolling/poll',
        })

    @http.route('/api/v1/poll', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def realtime_poll(self, channels=None, last=0, **kw):
        """Dedicated long-polling endpoint for the desktop agent / mobile app, sharing
        the same Bearer API key authentication (Odoo's native /longpolling/poll route
        requires a session cookie, which isn't compatible with an external API key
        client, hence this equivalent endpoint).

        Payload: { "channels": ["it_support_ticket_5"], "last": 0 }
        Returns as soon as a new notification is available, or an empty list after
        POLL_WAIT_SECONDS with none.

        IMPORTANT: bus.bus._poll() itself does NOT block - in this Odoo version the only
        actual waiting mechanism lives in the websocket layer (ImDispatch), which this
        Bearer-API-key client can't use (that requires a session cookie). Calling
        _poll() once and returning immediately - the original version of this method -
        turns the client's "call again right away" loop into a busy-loop with no delay
        at all, hammering the server many times a second per open chat and pegging CPU
        (this is exactly what happened in production - see incident notes). So this
        loops itself: check, and if nothing's there yet, sleep briefly and check again,
        up to POLL_WAIT_SECONDS, so a full round trip takes seconds rather than
        milliseconds and each client only calls back a couple of times a minute.
        """
        if not channels:
            return _json_error('Missing channels.')
        Bus = request.env['bus.bus'].sudo()
        deadline = time.monotonic() + POLL_WAIT_SECONDS
        try:
            while True:
                notifications = Bus._poll(channels, last)
                if notifications or time.monotonic() >= deadline:
                    return _json_ok(notifications)
                time.sleep(POLL_CHECK_INTERVAL_SECONDS)
        except Exception as e:
            _logger.exception('Long-polling error')
            return _json_error(str(e), status=500)


    @http.route('/api/v1/agent/login', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def agent_login(self, **kw):
        """Email + password login for the Desktop/Mobile Agent apps, so staff can sign
        in with the same credentials they already use for the Odoo web UI instead of
        having to be handed a manually-generated API key. Verifies via the same
        res.users.authenticate() Odoo's own /web/login uses (inheriting its brute-force
        lockout behavior), then - on success, for an Agent/Manager account only -
        mints a brand-new persistent API key and hands it back. Everything AFTER login
        keeps working exactly as before: the app stores this key and uses the existing
        Bearer-API-key endpoints for everything else, same as one pasted in manually.

        Payload: { "login": "agent@vmtech.ca", "password": "..." }

        Note: a new API key is generated on every login (Odoo API keys are stored as a
        one-way hash - there is no way to retrieve a previously-issued key's value
        again to reuse it). Old keys from earlier logins are not auto-revoked; an admin
        can clean them up under the user's Account Security settings if needed.
        """
        login = (kw.get('login') or '').strip()
        password = kw.get('password') or ''
        if not login or not password:
            return _json_error('Missing login or password.')

        try:
            auth_info = request.env['res.users'].authenticate(
                {'type': 'password', 'login': login, 'password': password},
                {'interactive': False},
            )
        except AccessDenied:
            return _json_error('Invalid email or password.', status=401)

        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        agent_group = request.env.ref('it_support_management.group_it_support_agent')
        manager_group = request.env.ref('it_support_management.group_it_support_manager')
        is_agent = agent_group in user.group_ids
        is_manager = manager_group in user.group_ids
        if not is_agent and not is_manager:
            return _json_error(
                'This account is not in the IT Support Agent/Manager group. Please contact your administrator.',
                status=403,
            )

        key_name = 'Agent app login - %s' % fields.Datetime.now()
        api_key = request.env['res.users.apikeys'].sudo().with_user(user)._generate(None, key_name, None)

        return _json_ok({
            'api_key': api_key,
            'user_id': user.id,
            'name': user.name,
            'email': user.email,
            'is_agent': is_agent,
            'is_manager': is_manager,
        })

    @http.route('/api/v1/whoami', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def whoami(self, **kw):
        """Trả về thông tin user hiện tại (dùng để xác thực API key và lấy identity agent).
        Flutter app gọi sau khi người dùng nhập API key để kiểm tra hợp lệ và lấy tên agent.
        """
        user = request.env.user
        agent_group = request.env.ref('it_support_management.group_it_support_agent')
        manager_group = request.env.ref('it_support_management.group_it_support_manager')
        return _json_ok({
            'user_id': user.id,
            'name': user.name,
            'email': user.email,
            'is_agent': agent_group in user.group_ids,
            'is_manager': manager_group in user.group_ids,
        })

    def _require_manager(self):
        """Returns an error dict if the current user isn't in the IT Support
        Manager group (Desktop/Mobile Agent app calls this before showing/acting
        on website Booking Requests - deliberately Manager-only, not Agent), else
        None so the caller can continue."""
        manager_group = request.env.ref('it_support_management.group_it_support_manager')
        if manager_group not in request.env.user.group_ids:
            return _json_error('This action requires IT Support Manager permission.', status=403)
        return None

    @http.route('/api/v1/booking/list', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def booking_list(self, **kw):
        """Manager-only: list pending website Booking Requests, so a manager
        using the Desktop/Mobile Agent app can review new customer requests,
        call them to confirm details, and open an initial ticket - without
        needing to log into the Odoo backend."""
        err = self._require_manager()
        if err:
            return err
        bookings = request.env['it.support.booking.request'].sudo().search(
            [('state', '=', 'pending')], order='create_date desc'
        )
        return _json_ok([{
            'id': b.id,
            'name': b.name,
            'company_type': b.company_type,
            'company_name': b.company_name,
            'email': b.email,
            'phone': b.phone,
            'requested_start': b.requested_start and fields.Datetime.to_string(b.requested_start),
            'duration': b.duration,
            'message': b.message,
            'create_date': fields.Datetime.to_string(b.create_date),
        } for b in bookings])

    @http.route('/api/v1/booking/<int:booking_id>/create_ticket', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def booking_create_ticket(self, booking_id, **kw):
        """Manager-only: confirms the booking (creating/linking the Customer if
        needed) and opens an initial ticket from it in one step."""
        err = self._require_manager()
        if err:
            return err
        booking = request.env['it.support.booking.request'].sudo().browse(booking_id)
        if not booking.exists():
            return _json_error('Booking request not found.', status=404)
        if booking.state == 'rejected':
            return _json_error('This booking request was already rejected.')
        if booking.ticket_id:
            return _json_error('A ticket was already created from this booking request.')
        ticket = booking.action_confirm_and_create_ticket()
        return _json_ok({
            'ticket_id': ticket.id,
            'ticket_name': ticket.name,
            'customer_id': booking.partner_id.id,
            'customer_name': booking.partner_id.name,
        })

    @http.route('/api/v1/agent/register_fcm_token', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def register_fcm_token(self, **kw):
        """Flutter app gửi FCM token lên Odoo mỗi khi app khởi động (token có thể
        thay đổi). Dùng device_fingerprint để upsert — không tạo duplicate.

        Payload: {
            "fcm_token": "eH3k...",
            "device_fingerprint": "a1b2c3d4"   # UUID lưu trong SharedPreferences
        }
        """
        fcm_token = kw.get('fcm_token')
        device_fingerprint = kw.get('device_fingerprint')
        if not fcm_token or not device_fingerprint:
            return _json_error('Missing fcm_token or device_fingerprint.')

        AgentDevice = request.env['it.support.agent.device'].sudo()
        existing = AgentDevice.search([
            ('agent_id', '=', request.env.user.id),
            ('device_fingerprint', '=', device_fingerprint),
        ], limit=1)

        if existing:
            existing.write({'fcm_token': fcm_token, 'last_seen': fields.Datetime.now()})
        else:
            AgentDevice.create({
                'agent_id': request.env.user.id,
                'device_fingerprint': device_fingerprint,
                'fcm_token': fcm_token,
                'last_seen': fields.Datetime.now(),
            })
        return _json_ok({'registered': True})

    # ---------------------------------------------------------------
    # MOBILE APP (IT SUPPORT AGENT) ENDPOINTS
    # ---------------------------------------------------------------

    @http.route('/api/v1/tickets', type='jsonrpc', auth='it_support_api_key', methods=['POST'], csrf=False)
    def ticket_list(self, **kw):
        """Called by the mobile app to get the ticket list (mine or unassigned).
        Query: ?state=new&mine=1
        """
        Ticket = request.env['it.support.ticket'].sudo()
        domain = []
        if kw.get('state'):
            domain.append(('state', '=', kw.get('state')))
        if kw.get('mine'):
            domain.append(('agent_id', '=', request.env.user.id))
        else:
            domain.append('|')
            domain.append(('agent_id', '=', request.env.user.id))
            domain.append(('agent_id', '=', False))

        tickets = Ticket.search(domain, order='priority desc, create_date desc', limit=100)
        return _json_ok([{
            'id': t.id,
            'name': t.name,
            'subject': t.subject,
            'customer': t.customer_id.name,
            'device': t.device_id.name,
            'support_type': t.support_type_id.name,
            'priority': t.priority,
            'state': t.state,
            'agent': t.agent_id.name if t.agent_id else None,
        } for t in tickets])

    @http.route('/api/v1/ticket/<int:ticket_id>', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_detail(self, ticket_id, **kw):
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        running_session = ticket.session_ids.filtered(lambda s: s.state == 'running')[:1]
        return _json_ok({
            'id': ticket.id,
            'name': ticket.name,
            'subject': ticket.subject,
            'description': ticket.description,
            'customer': ticket.customer_id.name,
            'device': ticket.device_id.name,
            'end_user': ticket.end_user_id.name,
            'support_type': ticket.support_type_id.name,
            'priority': ticket.priority,
            'state': ticket.state,
            'agent': ticket.agent_id.name if ticket.agent_id else None,
            'total_duration': ticket.total_duration,
            'billable_hours': ticket.billable_hours,
            'amount_total': ticket.amount_total,
            'has_running_session': bool(running_session),
            # UTC naive datetime string (Odoo convention), e.g. "2026-07-17 10:30:00".
            # Client is responsible for treating this as UTC when computing elapsed time.
            'running_session_start': str(running_session.start_time) if running_session else None,
        })

    @http.route('/api/v1/ticket/<int:ticket_id>/assign', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_assign(self, ticket_id, **kw):
        """On-duty agent picks up a ticket from the mobile app."""
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        ticket.with_user(request.env.user).action_assign_to_me()
        return _json_ok({'ticket_id': ticket.id, 'state': ticket.state, 'agent': ticket.agent_id.name})

    @http.route('/api/v1/ticket/<int:ticket_id>/session/start', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def session_start(self, ticket_id, **kw):
        """Agent taps Start on the mobile app when starting to work on a ticket.
        Payload: { "support_mode": "onsite" | "online" }
        """
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        try:
            session = ticket.with_user(request.env.user).action_start_session(
                support_mode=kw.get('support_mode')
            )
        except Exception as e:
            return _json_error(str(e))
        return _json_ok({
            'session_id': session.id,
            'ticket_id': ticket.id,
            'start_time': str(session.start_time),
            'support_mode': session.support_mode,
        })

    @http.route('/api/v1/ticket/<int:ticket_id>/session/end', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def session_end(self, ticket_id, **kw):
        """Agent taps End on the mobile app when finishing work.
        Payload: {
            "note": "Replaced the printer driver.",              # REQUIRED - work performed
            "resolution_status": "resolved"                      # REQUIRED - one of:
                                                                   # resolved / partially_resolved /
                                                                   # not_resolved / escalated
        }
        Both fields are mandatory: the mobile app must force the agent to fill
        them in on the End-session screen before this call is made, and the
        underlying it.support.session model rejects the close if either is
        missing (see it_support_session.py: action_end_session).
        """
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)

        note = kw.get('note')
        resolution_status = kw.get('resolution_status')
        if not note or not str(note).strip():
            return _json_error('Missing note: please describe the work performed.')
        valid_resolution_statuses = ('resolved', 'partially_resolved', 'not_resolved', 'escalated')
        if resolution_status not in valid_resolution_statuses:
            return _json_error(
                "Missing or invalid resolution_status: must be one of %s." % ', '.join(valid_resolution_statuses)
            )

        try:
            # NOTE: it.support.ticket.action_end_session() (in it_support_ticket.py,
            # not shown here) must forward BOTH kwargs to the running
            # it.support.session record, e.g.:
            #   running_session.action_end_session(note=note, resolution_status=resolution_status)
            # If it currently only forwards `note`, it needs to be updated to also
            # accept and forward `resolution_status` - otherwise this call will
            # raise a TypeError or silently drop the resolution status.
            ticket.with_user(request.env.user).action_end_session(
                note=note, resolution_status=resolution_status
            )
        except Exception as e:
            return _json_error(str(e))

        running_session = ticket.session_ids.filtered(lambda s: s.state == 'closed').sorted('end_time', reverse=True)[:1]
        return _json_ok({
            'ticket_id': ticket.id,
            'duration': running_session.duration if running_session else 0,
            'total_duration': ticket.total_duration,
        })

    @http.route('/api/v1/ticket/<int:ticket_id>/done', type='jsonrpc', auth='it_support_api_key',
                methods=['POST'], csrf=False)
    def ticket_done(self, ticket_id, **kw):
        """Agent marks the ticket as completed."""
        ticket = request.env['it.support.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return _json_error('Ticket not found.', status=404)
        ticket.with_user(request.env.user).action_done()
        return _json_ok({'ticket_id': ticket.id, 'state': ticket.state})
