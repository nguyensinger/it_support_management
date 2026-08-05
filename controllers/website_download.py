# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

INSTALLER_ATTACHMENT_NAME = 'VM TECH Support Client Setup.exe'


class WebsiteDownload(http.Controller):

    def _get_client_installer(self):
        return request.env['ir.attachment'].sudo().search([
            ('name', '=', INSTALLER_ATTACHMENT_NAME),
            ('public', '=', True),
        ], limit=1, order='create_date desc')

    @http.route('/download', type='http', auth='public', website=True, sitemap=True)
    def download_page(self, **kw):
        return request.render('it_support_management.page_downloads', {
            'client_installer': self._get_client_installer(),
        })

    @http.route('/download/client-windows', type='http', auth='public', website=True)
    def download_client_windows(self, **kw):
        installer = self._get_client_installer()
        if not installer:
            return request.not_found()
        return request.redirect('/web/content/%s?download=true' % installer.id)
