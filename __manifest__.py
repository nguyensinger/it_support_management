# -*- coding: utf-8 -*-
{
    'name': 'IT Support Management',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Customer IT support management: devices, tickets, onsite/online, time tracking, billing',
    'description': """
IT Support Management
======================
IT support service management module for customers:

* Manage customers, devices, and end users
* Manage support types (Onsite/Online), pricing, and billing block rules
* Manage support tickets, working sessions (start/end session)
* Monthly summary report per customer
* Generate invoices from monthly summaries
* Project management (network/camera installs, custom software) with tasks,
  input costs (vendor bills), deposit + final invoicing
* General company expense tracking
* REST API for the Desktop Agent and Mobile App (IT support)
""",
    'author': 'Your Company',
    'website': 'https://www.example.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'contacts',
        'account',
        'account_payment',
        'product',
        'sale',
        'website',
        'portal',
        'l10n_ca',
        'auth_signup',
        'auth_totp_mail',
    ],
    'data': [
        # security
        'security/it_support_security.xml',
        'security/ir.model.access.csv',
        # data
        'data/ir_sequence_data.xml',
        'data/it_support_sla_data.xml',
        'data/it_support_type_data.xml',
        'data/ir_cron_data.xml',
        'data/it_support_server_action_data.xml',
        'data/it_support_mail_template_data.xml',
        'data/it_support_payment_method_data.xml',
        # views
        'views/it_customer_device_views.xml',
        'views/it_support_end_user_views.xml',
        'views/it_support_type_views.xml',
        'views/it_support_ticket_views.xml',
        'views/it_support_session_views.xml',
        'views/it_support_duty_schedule_views.xml',
        'views/it_support_monthly_summary_views.xml',
        'views/it_support_generate_summary_wizard_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_bank_views.xml',
        'views/res_company_views.xml',
        'views/res_users_views.xml',
        'views/it_support_sla_views.xml',
        'views/it_support_agent_payroll_views.xml',
        'views/it_support_agent_payroll_generate_wizard_views.xml',
        'views/it_expense_category_views.xml',
        'views/it_support_menus.xml',
        'views/it_project_project_views.xml',
        'views/it_project_menus.xml',
        'views/it_support_business_hours_views.xml',
        'views/it_support_booking_request_views.xml',
        'views/website_booking_templates.xml',
        'views/website_footer_templates.xml',
        'views/website_header_booking_button.xml',
        'views/website_debrand_templates.xml',
        'views/website_download_templates.xml',
        'views/it_support_portal_templates.xml',
        # report
        'report/it_support_monthly_report.xml',
        'report/it_support_monthly_report_templates.xml',
        'report/it_support_invoice_report_templates.xml',
    ],
    'demo': [
        'data/it_support_demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
