from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    api_key = fields.Char(string="API Key", config_parameter="deepseek_r1.api_key", required=True)
