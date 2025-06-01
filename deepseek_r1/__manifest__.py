# -*- coding: utf-8 -*-
{
    'name': "DeepSeek R1",

    'summary': "DeepSeek Intergration with Odoo",

    'description': """
         Integrating DeepSeek with Odoo can enhance your ERP system with advanced AI capabilities.
    """,

    'author': "Hari",
    'website': "https://hari1119.github.io/",
    'version': '0.1',
    'external_dependencies': {
        'python': ['openai'],  # List any Python libraries required
    },
    'depends': ['base', 'base_setup', 'mail'],
    'images': ['static/description/banner.gif'],
    'data': [
        'data/mail_channel_data.xml',
        'data/user_partner_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'license': 'GPL-3',
}

