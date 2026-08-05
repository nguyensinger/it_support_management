# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

WINDOWS_INSTALLER_NAME = 'VM TECH Support Client Setup.exe'
MAC_INSTALLER_NAME = 'VM TECH Support Client.dmg'


class WebsiteDownload(http.Controller):

    def _get_installer(self, name):
        return request.env['ir.attachment'].sudo().search([
            ('name', '=', name),
            ('public', '=', True),
        ], limit=1, order='create_date desc')

    @http.route('/download', type='http', auth='public', website=True, sitemap=True)
    def download_page(self, **kw):
        return request.render('it_support_management.page_downloads', {
            'client_installer': self._get_installer(WINDOWS_INSTALLER_NAME),
            'mac_installer': self._get_installer(MAC_INSTALLER_NAME),
        })

    @http.route('/download/client-windows', type='http', auth='public', website=True)
    def download_client_windows(self, **kw):
        installer = self._get_installer(WINDOWS_INSTALLER_NAME)
        if not installer:
            return request.not_found()
        return request.redirect('/web/content/%s?download=true' % installer.id)

    @http.route('/download/client-mac', type='http', auth='public', website=True)
    def download_client_mac(self, **kw):
        installer = self._get_installer(MAC_INSTALLER_NAME)
        if not installer:
            return request.not_found()
        return request.redirect('/web/content/%s?download=true' % installer.id)
