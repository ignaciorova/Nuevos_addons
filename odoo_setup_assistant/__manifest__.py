# -*- coding: utf-8 -*-
{
    'name': 'Odoo Setup Assistant',
    'module_name': 'odoo_setup_assistant',
    'version': '3.0.2', # Incremented version for new features
    'summary': 'Diagnose Odoo setup, configuration, dependencies, and manage addon Python requirements.',
    'description': 'static/description/index.html',
    'author': 'ECOSIRE (PRIVATE) LIMITED',
    'website': 'https://www.ecosire.com/',
    'category': 'Extra Tools', # Or 'Administration', 'Technical'
    'depends': ['base', 'mail'], # Depends on the base Odoo module and mail for mail.thread/activity
    'data': [
        'security/ir.model.access.csv',
        'views/menu.xml',
        'views/github_repo_views.xml',
        'views/odoo_setup_assistant_views.xml',
        'views/res_config_settings_views.xml',
        'data/setup_assist_data.xml',
        # Add security CSV if specific groups beyond base.group_system are needed later
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
    'compatible_version': '18.0',
    'images': ['static/description/cover.png'],
    # It's good practice to note external Python dependencies if your module *itself*
    # directly depends on something not standard in Odoo's core requirements.
    # For the 'packaging' library used by addon_requirements_checker.py,
    # it's often present with pip/setuptools. If it were less common, you might note it here.
    # 'external_dependencies': {'python': ['packaging']}, # Example
}