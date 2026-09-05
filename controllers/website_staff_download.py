# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

WINDOWS_INSTALLER_NAME = 'VM TECH Desktop Support Setup 1.0.0.exe'
MAC_INSTALLER_NAME = 'VM TECH Desktop Support-1.0.0-universal.dmg'


class WebsiteStaffDownload(http.Controller):
    """Download page for the internal VM TECH Desktop Support app - staff only
    (IT Support Agent/Manager), unlike /download which is the public page for
    customers to get the VM TECH Support Client."""

    def _get_installer(self, name):
        return request.env['ir.attachment'].sudo().search([
            ('name', '=', name),
            ('public', '=', True),
        ], limit=1, order='create_date desc')

    @http.route('/staff/download', type='http', auth='user', website=True, sitemap=False)
    def staff_download_page(self, **kw):
        if not request.env.user.has_group('it_support_management.group_it_support_agent'):
            return request.not_found()
        return request.render('it_support_management.page_staff_downloads', {
            'windows_installer': self._get_installer(WINDOWS_INSTALLER_NAME),
            'mac_installer': self._get_installer(MAC_INSTALLER_NAME),
        })

    @http.route('/staff/download/windows', type='http', auth='user', website=True)
    def staff_download_windows(self, **kw):
        if not request.env.user.has_group('it_support_management.group_it_support_agent'):
            return request.not_found()
        installer = self._get_installer(WINDOWS_INSTALLER_NAME)
        if not installer:
            return request.not_found()
        return request.redirect('/web/content/%s?download=true' % installer.id)

    @http.route('/staff/download/mac', type='http', auth='user', website=True)
    def staff_download_mac(self, **kw):
        if not request.env.user.has_group('it_support_management.group_it_support_agent'):
            return request.not_found()
        installer = self._get_installer(MAC_INSTALLER_NAME)
        if not installer:
            return request.not_found()
        return request.redirect('/web/content/%s?download=true' % installer.id)
