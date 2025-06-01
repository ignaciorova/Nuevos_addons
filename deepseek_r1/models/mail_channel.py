from odoo.exceptions import UserError, ValidationError
import requests
from odoo import api, fields, models, _

def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
        __import__(package)

# Check and install the openai package
install_and_import('openai')

from openai import OpenAI

global messages_history
messages_history = []

class CommunicationChannel(models.Model):
    _inherit = 'discuss.channel'

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        rdata = super(CommunicationChannel, self)._notify_thread(message, msg_vals=msg_vals, **kwargs)
        deepseek_r1_id = self.env.ref('deepseek_r1.channel_deepseek_r1')
        user_deepseek_r1 = self.env.ref("deepseek_r1.user_deepseek_r1")
        partner_deepseek_r1 = self.env.ref("deepseek_r1.partner_deepseek_r1")
        author_id = msg_vals.get('author_id')
        deepseek_r1_name = str(partner_deepseek_r1.name or '') + ', '
        prompt = msg_vals.get('body')

        if not prompt:
            return rdata
        try:
            if author_id != partner_deepseek_r1.id:
                res = self._get_deepseek_r1_response(prompt=prompt)
                self.with_user(user_deepseek_r1).message_post(body=res, message_type='comment', subtype_xmlid='mail.mt_comment')
            elif author_id != partner_chatgpt.id and msg_vals.get('model', '') == 'discuss.channel' and msg_vals.get('res_id', 0) == deepseek_r1_id.id:
                res = self._get_deepseek_r1_response(prompt=prompt)
                deepseek_r1_id.with_user(user_deepseek_r1).message_post(body=res, message_type='comment', subtype_xmlid='mail.mt_comment')

        except Exception as e:
            # Log or handle exceptions more specifically
            pass

        return rdata

    def _get_deepseek_r1_response(self, prompt):
        ICP = self.env['ir.config_parameter'].sudo()
        config_api_key = ICP.get_param('deepseek_r1.api_key')
        
        client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config_api_key,
        )
        
        messages_history.append({
            "role": "user",
            "content": prompt,
            })

        completion = client.chat.completions.create(
        extra_headers={},
        model="openai/gpt-3.5-turbo",
        messages= messages_history
        )
        try:
            return completion.choices[0].message.content
        except requests.exceptions.RequestException as e:
            raise UserError("Please enter valid DeepSeek api key.")
        except Exception as e:
            return e
