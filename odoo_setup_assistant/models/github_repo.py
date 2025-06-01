# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import subprocess
import logging
import os

_logger = logging.getLogger(__name__)

class SetupAssistGithubRepo(models.Model):
    _name = 'setup.assist.github.repo'
    _description = 'Odoo Setup Assistant Github Repository'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Repository Name', required=True, tracking=True)
    repo_url = fields.Char(string='Repository URL (HTTPS or SSH)', required=True, tracking=True)
    branch = fields.Char(string='Branch/Tag (e.g., main, 16.0, v1.0.0)', required=True, default='main', tracking=True)
    target_addons_path = fields.Char(string='Target Addons Subdirectory', required=True, tracking=True,
                                     help='Relative path within an Odoo addons directory where this repo should be cloned/pulled. Example: `custom_addons/my_module_folder`')
    github_username = fields.Char(string='GitHub Username', tracking=True, help='Required for private repositories or token authentication.')
    github_pat = fields.Char(string='Personal Access Token (PAT)', tracking=True, groups='base.group_system', password=True, help='Required for private repositories or token authentication.')
    active = fields.Boolean(string='Active', default=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    last_git_log = fields.Text(string='Last Git Operation Log', readonly=True)
    last_git_status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('pending', 'Pending'),
        ('not_run', 'Not Run Yet'),
    ], string='Last Git Operation Status', readonly=True, default='not_run')

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Repository name must be unique.'),
        ('repo_path_unique', 'unique(repo_url, target_addons_path)', 'This repository URL is already configured to be cloned to this target path.'),
    ]

    def _get_git_authenticated_url(self):
        """ Constructs the authenticated git URL if credentials are provided. """
        if self.github_username and self.github_pat:
            # Assumes HTTPS URL format like https://github.com/user/repo.git
            if self.repo_url.startswith('https://'):
                 # Embed username and PAT in the URL
                return self.repo_url.replace('https://', f'https://{self.github_username}:{self.github_pat}@')
            # SSH URLs typically use SSH keys and don't embed credentials like this
            elif self.repo_url.startswith('git@'):
                 _logger.warning(f"SSH URL {self.repo_url} provided for repo {self.name}. Credentials via PAT field will not be used. Ensure Odoo user has SSH access.")
                 return self.repo_url # SSH authentication relies on server-side keys
            else:
                 _logger.warning(f"Repository URL {self.repo_url} for repo {self.name} has an unrecognized format. Cannot embed credentials.")
                 return self.repo_url
        return self.repo_url # No credentials provided or needed

    def _execute_git_command(self, command_list, cwd=None):
        """ Executes a git command and returns output and status. """
        self.ensure_one() # Should be called on a single record
        try:
            _logger.info(f"Executing git command: {' '.join(command_list)} in {cwd or '.'}")
            process = subprocess.run(command_list, cwd=cwd, capture_output=True, text=True, check=True, shell=False)
            self.last_git_log = process.stdout + process.stderr
            self.last_git_status = 'success'
            self.message_post(body=_(f'Git command executed successfully for {self.name}.'))
            _logger.info(f"Git command successful for {self.name}")
            return True, process.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.last_git_log = e.stdout + e.stderr
            self.last_git_status = 'error'
            error_message = _(f'Git command failed for {self.name} (Exit Code {e.returncode}):\n{e.stdout}\n{e.stderr}')
            self.message_post(body=error_message)
            _logger.error(f"Git command failed for {self.name}: {e.stdout} {e.stderr}")
            return False, error_message
        except FileNotFoundError:
             self.last_git_log = "Git executable not found." # Specific error for missing git
             self.last_git_status = 'error'
             error_message = _("Git executable not found. Please ensure Git is installed on the server and in the system's PATH.")
             self.message_post(body=error_message)
             _logger.error("Git executable not found.")
             return False, error_message
        except Exception as e:
            self.last_git_log = str(e)
            self.last_git_status = 'error'
            error_message = _(f'An unexpected error occurred during git operation for {self.name}: {e}')
            self.message_post(body=error_message)
            _logger.exception(f"Unexpected error during git operation for {self.name}")
            return False, error_message

    def action_clone_or_pull(self):
        """ Clones the repository if the target path is empty, otherwise pulls. """
        self.ensure_one()
        # Get Odoo addons paths from config. This requires system parameter `addons_path` to be set.
        # Alternatively, we could try to guess based on known Odoo install structures,
        # but relying on odoo.conf or ir.config_parameter is more robust.

        # Need to find the base addons path where target_addons_path resides
        # This is complex as target_addons_path is a subdirectory, not the full path
        # The user needs to specify the full path or we need a setting for base repo dir
        # Let's assume `target_addons_path` is the FULL path for simplicity initially,
        # or add a config parameter for the base repository directory.

        # Let's add an ir.config_parameter for the base git cloning directory
        base_git_dir = self.env['ir.config_parameter'].sudo().get_param('setup.assist.base_git_dir')
        if not base_git_dir:
             raise UserError(_("Please configure the 'Base Git Cloning Directory' in Setup Assistant settings."))

        target_path = os.path.join(base_git_dir, self.target_addons_path)

        # Ensure the parent directory exists
        parent_dir = os.path.dirname(target_path)
        if not os.path.exists(parent_dir):
             try:
                 os.makedirs(parent_dir)
                 _logger.info(f"Created parent directory: {parent_dir}")
             except OSError as e:
                 error_message = _(f"Error creating parent directory {parent_dir}: {e}")
                 self.last_git_log = str(e)
                 self.last_git_status = 'error'
                 self.message_post(body=error_message)
                 _logger.error(error_message)
                 return False, error_message

        if os.path.exists(target_path):
            # Check if it's a git repository
            git_check_command = ['git', 'rev-parse', '--is-inside-work-tree']
            is_git_repo, _ = self._execute_git_command(git_check_command, cwd=target_path)

            if is_git_repo:
                # It's a git repo, perform git pull
                self.message_post(body=_('Attempting to pull updates for %s...') % self.name)
                fetch_command = ['git', 'fetch', 'origin', self.branch]
                success, _ = self._execute_git_command(fetch_command, cwd=target_path)
                if not success:
                    return False, "Fetch failed."

                pull_command = ['git', 'reset', '--hard', f'origin/{self.branch}'] # Use reset hard to overwrite local changes
                success, output = self._execute_git_command(pull_command, cwd=target_path)

                if success:
                    self.message_post(body=_('Successfully pulled updates for %s.') % self.name)
                    return True, output
                else:
                    return False, output
            else:
                # Path exists but is not a git repo, error out or attempt to clone into it?
                # Error out to prevent data loss or unexpected behavior.
                error_message = _(f"Target path {target_path} exists but is not a Git repository.")
                self.last_git_log = error_message
                self.last_git_status = 'error'
                self.message_post(body=error_message)
                _logger.error(error_message)
                return False, error_message
        else:
            # Path does not exist, perform git clone
            self.message_post(body=_('Attempting to clone %s...') % self.name)
            # Use parent_dir as cwd for clone command
            authenticated_url = self._get_git_authenticated_url()
            # Clone directly into the target_addons_path relative to parent_dir
            clone_command = ['git', 'clone', '--depth', '1', '--branch', self.branch, authenticated_url, self.target_addons_path]
            success, output = self._execute_git_command(clone_command, cwd=parent_dir)

            if success:
                 self.message_post(body=_('Successfully cloned %s.') % self.name)
                 return True, output
            else:
                 return False, output

    def action_restart_odoo(self):
        """ Triggers the Odoo service restart. """
        # This will call the existing logic in the wizard or dependency installer
        # For now, we can leave this abstract or call the wizard action
        # Let's add a method here and call it from the wizard later
        self.ensure_one()
        # Need a way to call the restart logic, ideally from a central place
        # For now, let's add a placeholder message
        self.message_post(body=_('Odoo service restart requested via Setup Assistant.'))
        _logger.info(f"Odoo service restart requested for repo {self.name} related update.")

        # Here we would ideally call the restart logic from the wizard or a dedicated installer model
        # For now, this method exists primarily as a place to potentially trigger it later

    def action_clone_pull_and_restart(self):
        """ Performs clone/pull and then triggers Odoo restart. """
        self.ensure_one()
        success, message = self.action_clone_or_pull()
        if success:
            # Trigger Odoo restart after successful git operation
            # We need a way to call the wizard's restart action or a dedicated installer method
            # For simplicity now, let's just log and post a message.
            # Integration with the actual restart action will be done from the wizard side.
            self.message_post(body=_('Git operation successful. Proceeding to request Odoo service restart...'))
            _logger.info("Git operation successful, requesting Odoo restart.")
            # In the wizard, we'll call this action for each selected repo, then trigger the global restart action.
        else:
            self.message_post(body=_('Git operation failed. Odoo service will not be restarted.'))
            _logger.error("Git operation failed, Odoo restart skipped.") 