# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
# from odoo.exceptions import UserError # Not used yet, but good for future
import logging
import platform
import psutil
import shutil
import os
import json
from odoo import release as odoo_release

_logger = logging.getLogger(__name__)

# Import all checkers
from ..checkers import system_checks
from ..checkers import db_checks
from ..checkers import conf_checks
from ..checkers import addon_requirements_checker
from ..checkers import log_analyzer # Import the new log analyzer


class SetupAssistWizard(models.TransientModel):
    _name = 'setup.assist.wizard'
    _description = 'Odoo Setup Assistant Wizard'

    # --- General ---
    general_message = fields.Text(string="Status Messages", readonly=True)

    # --- Dependency Check Fields ---
    python_dependencies_results = fields.Text(string="Python Dependencies Check", readonly=True)
    system_dependencies_results = fields.Text(string="System Dependencies Check", readonly=True)
    overall_dependency_status = fields.Selection([
        ('not_run', 'Not Run Yet'), ('ok', 'OK'), ('issues', 'Issues Found')
    ], string="Overall Dependency Status", default='not_run', readonly=True)

    # --- Database Check Fields ---
    db_connection_results = fields.Text(string="Database Connection Check", readonly=True)
    db_status = fields.Selection([
        ('not_run', 'Not Run Yet'), ('ok', 'OK'), ('issues', 'Issues Found'), ('warning', 'Warnings')
    ], string="Database Status", default='not_run', readonly=True)

    # --- Odoo.conf Check Fields ---
    odoo_conf_results = fields.Text(string="Odoo.conf Analysis", readonly=True)
    odoo_conf_status = fields.Selection([
        ('not_run', 'Not Run Yet'), ('ok', 'OK'), ('issues', 'Issues Found'), ('warning', 'Warnings')
    ], string="Odoo.conf Status", default='not_run', readonly=True)

    # --- Addon Python Dependencies Fields ---
    addon_req_scan_results = fields.Text(string="Scan Results for Addon Python Deps", readonly=True)
    addon_req_install_log = fields.Text(string="Installation Log for Addon Python Deps", readonly=True)
    addon_req_status = fields.Selection([
        ('not_run', 'Not Run Yet'),
        ('scanned_ok', 'Scan: All Satisfied'),
        ('scanned_issues', 'Scan: Missing Deps Found'),
        ('scanned_error', 'Scan: Error Occurred'),
        ('install_inprogress', 'Installation In Progress...'),
        ('install_done_ok', 'Install: Successful'),
        ('install_done_errors', 'Install: Errors Occurred'),
        ('install_failed', 'Install: Critical Failure')
    ], string="Addon Python Deps Status", default='not_run', readonly=True)
    packages_to_install_list = fields.Text(string="Packages to Install (Internal JSON/CSV)", readonly=True,
                                           help="Internal field to store package specs for installation.")

    # --- Log File Analysis Fields (New) ---
    log_file_path_display = fields.Char(string="Detected Log File Path", readonly=True)
    log_lines_to_fetch = fields.Integer(string="Recent Lines to Fetch", default=200, required=True)
    log_level_filter = fields.Selection([
        ('ALL', 'ALL Levels'),
        ('DEBUG', 'DEBUG'),
        ('INFO', 'INFO'),
        ('WARNING', 'WARNING'),
        ('ERROR', 'ERROR'),
        ('CRITICAL', 'CRITICAL'),
    ], string="Filter by Log Level", default='ALL', required=True)
    log_keyword_filter = fields.Char(string="Filter by Keyword (case-insensitive)")
    
    log_display_content = fields.Text(string="Log Entries", readonly=True)
    log_diagnostic_hints = fields.Text(string="Diagnostic Hints", readonly=True)
    log_analysis_status = fields.Selection([
        ('not_run', 'Not Run Yet'),
        ('success', 'Logs Loaded'),
        ('no_log_file', 'Log File Not Configured/Found'),
        ('error_reading', 'Error Reading Log File'),
        ('empty_after_filter', 'No Logs Found Matching Filters')
    ], string="Log Analysis Status", default='not_run', readonly=True)

    # --- GitHub Integration Fields ---
    github_repo_ids = fields.Many2many(
        'setup.assist.github.repo', string='Select Repositories to Update',
        help='Select the GitHub repositories you want to clone/pull updates for.'
    )

    # --- Placeholder for other checks ---
    port_check_results = fields.Text(string="Network Port Check", readonly=True, default="Not implemented yet.")
    file_permissions_results = fields.Text(string="File Permissions Check", readonly=True, default="Not implemented yet.")

    system_info = fields.Text(string="System Information", compute="_compute_system_info")
    system_cpu_percent = fields.Float(string="CPU Usage (%)", compute="_compute_system_info")
    system_mem_percent = fields.Float(string="Memory Usage (%)", compute="_compute_system_info")
    system_mem_total = fields.Char(string="Total Memory", compute="_compute_system_info")
    system_mem_used = fields.Char(string="Used Memory", compute="_compute_system_info")
    system_disk_percent = fields.Float(string="Disk Usage (%)", compute="_compute_system_info")
    system_disk_total = fields.Char(string="Total Disk", compute="_compute_system_info")
    system_disk_used = fields.Char(string="Used Disk", compute="_compute_system_info")
    system_uptime = fields.Char(string="Uptime", compute="_compute_system_info")
    system_os = fields.Char(string="OS", compute="_compute_system_info")
    system_python = fields.Char(string="Python Version", compute="_compute_system_info")
    system_odoo = fields.Char(string="Odoo Version", compute="_compute_system_info")
    system_graph_data = fields.Text(string="System Graph Data (JSON)", compute="_compute_system_info")

    @api.model
    def default_get(self, fields_list):
        res = super(SetupAssistWizard, self).default_get(fields_list)
        res.update({
            'general_message': "Click buttons to perform checks or analysis.",
            'python_dependencies_results': "Click 'Run Dependency Checks' or 'Run All Scans'.",
            'system_dependencies_results': "Click 'Run Dependency Checks' or 'Run All Scans'.",
            'db_connection_results': "Click 'Check Database' or 'Run All Scans'.",
            'odoo_conf_results': "Click 'Analyze Odoo.conf' or 'Run All Scans'.",
            'addon_req_scan_results': "Click 'Scan Addon Python Dependencies'.",
            'addon_req_install_log': "No installation performed yet.",
            'packages_to_install_list': "",
            # Defaults for new log analysis fields
            'log_display_content': "Logs not loaded yet. Configure options and click 'Load & Analyze Logs'.",
            'log_diagnostic_hints': "No specific issues diagnosed yet.",
            'log_file_path_display': "Log file path will be shown after attempting to load logs.",
        })
        # Initialize log_file_path_display by trying to get it immediately
        try:
            la = log_analyzer.LogAnalyzer()
            res['log_file_path_display'] = la.log_file_path or "Not configured in odoo.conf"
        except Exception:
            res['log_file_path_display'] = "Error determining log file path."
        return res

    def _reopen_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # --- Dependency Checks --- (Keep existing methods)
    def _format_dependency_results(self):
        dep_checker = system_checks.DependencyChecker()
        py_missing, py_found = dep_checker.check_python_libraries()
        sys_missing, sys_found = dep_checker.check_system_dependencies()

        py_lines = []
        if py_missing: py_lines.append(f"🔴 MISSING Python Libraries ({len(py_missing)}):\n- " + "\n- ".join(py_missing))
        else: py_lines.append("✅ All checked Python libraries seem to be installed.")
        self.python_dependencies_results = "\n".join(py_lines)

        sys_lines = []
        if sys_missing:
            sys_lines.append(f"🔴 MISSING System Dependencies ({len(sys_missing)}):")
            for item in sys_missing: sys_lines.append(f"- {item['name']} (Hint: {item.get('hint', 'N/A')})")
        else: sys_lines.append("✅ All checked system dependencies seem available.")
        self.system_dependencies_results = "\n".join(sys_lines)

        self.overall_dependency_status = 'issues' if py_missing or sys_missing else 'ok'

    def action_run_dependency_checks(self):
        self.ensure_one()
        self._format_dependency_results()
        self.general_message = "Dependency checks completed."

    # --- Database Checks --- (Keep existing methods)
    def _format_db_check_results(self):
        try:
            db_checker = db_checks.DatabaseChecker(self.env)
            results, status = db_checker.perform_all_db_checks()
            self.db_connection_results = "\n".join(results)
            self.db_status = status
        except Exception as e:
            self.db_connection_results = f"ERROR during database check: {str(e)}"
            self.db_status = 'issues'
            _logger.exception("Error formatting DB check results")

    def action_run_db_checks(self):
        self.ensure_one()
        self._format_db_check_results()
        self.general_message = "Database checks completed."

    # --- Odoo.conf Checks --- (Keep existing methods)
    def _format_odoo_conf_results(self):
        try:
            checker = conf_checks.OdooConfigChecker()
            results, status = checker.perform_conf_checks()
            self.odoo_conf_results = "\n".join(results)
            self.odoo_conf_status = status
        except Exception as e:
            self.odoo_conf_results = f"ERROR during odoo.conf analysis: {str(e)}"
            self.odoo_conf_status = 'issues'
            _logger.exception("Error formatting odoo.conf check results")

    def action_run_odoo_conf_checks(self):
        self.ensure_one()
        self._format_odoo_conf_results()
        self.general_message = "Odoo.conf analysis completed."

    # --- Addon Python Dependency Checks & Installation --- (Keep existing methods)
    def _update_addon_req_ui_fields(self, scan_summary_lines=None, install_log_lines=None, status=None, packages_to_install_str=None):
        if scan_summary_lines is not None:
            self.addon_req_scan_results = "\n".join(scan_summary_lines)
        if install_log_lines is not None:
            self.addon_req_install_log = "\n".join(install_log_lines)
        if status is not None:
            self.addon_req_status = status
        if packages_to_install_str is not None:
            self.packages_to_install_list = packages_to_install_str

    def action_scan_addon_python_dependencies(self):
        self.ensure_one()
        self._update_addon_req_ui_fields(
            scan_summary_lines=["Scanning addon dependencies..."],
            install_log_lines=["No installation performed yet."],
            status='scanned_error', 
            packages_to_install_str=""
        )
        try:
            checker = addon_requirements_checker.AddonRequirementsChecker()
            analysis = checker.analyze_dependencies()
            to_install_specs = [item['package_spec'] for item in analysis.get('to_install', [])]
            self._update_addon_req_ui_fields(
                scan_summary_lines=analysis.get('summary_lines', ['Scan completed with no summary.']),
                packages_to_install_str=";;;".join(to_install_specs) if to_install_specs else ""
            )
            current_status = 'scanned_error'
            if analysis.get('errors'):
                current_status = 'scanned_error'
                self.addon_req_scan_results += "\n\nERRORS occurred during scan. Check Odoo server logs."
            elif not to_install_specs:
                current_status = 'scanned_ok'
            else:
                current_status = 'scanned_issues'
                warning_msg = ("\n\n--- ACTION REQUIRED ---\nMissing dependencies found. Click 'Install Discovered Dependencies'.")
                self.addon_req_scan_results += warning_msg
            self.addon_req_status = current_status
        except Exception as e:
            _logger.error(f"Critical error during addon dependency scan action: {e}", exc_info=True)
            self._update_addon_req_ui_fields(scan_summary_lines=[f"A critical error occurred during scan: {e}"], status='scanned_error')

    def action_install_addon_python_dependencies(self):
        self.ensure_one()
        if not self.packages_to_install_list:
            self._update_addon_req_ui_fields(install_log_lines=["No packages were marked for installation. Scan first."])
            return
        self._update_addon_req_ui_fields(status='install_inprogress', install_log_lines=["Starting installation...\n"])
        packages_specs = [spec.strip() for spec in self.packages_to_install_list.split(';;;') if spec.strip()]
        try:
            checker = addon_requirements_checker.AddonRequirementsChecker()
            install_results = checker.install_packages(packages_specs)
            self._update_addon_req_ui_fields(install_log_lines=install_results.get('log_lines', ['No installation log.']))
            current_status = 'install_failed'
            if install_results.get('failed'):
                current_status = 'install_done_errors'
                failed_specs = list(install_results.get('failed', {}).keys())
                self.packages_to_install_list = ";;;".join(failed_specs) if failed_specs else ""
                self.addon_req_install_log += "\n\nSome packages failed. Try 'Install' again for failed items."
            else:
                current_status = 'install_done_ok'
                self.packages_to_install_list = ""
                self.addon_req_install_log += "\n\nAll packages processed successfully."
            self.addon_req_status = current_status
            self.addon_req_install_log += "\n\nRecommended: 'Scan Addon Python Dependencies' again to verify."
        except Exception as e:
            _logger.error(f"Critical error during addon dependency installation action: {e}", exc_info=True)
            self._update_addon_req_ui_fields(
                install_log_lines=[self.addon_req_install_log or "", f"\nA critical error occurred: {e}"],
                status='install_failed'
            )

    # --- Log File Analysis (New Method) ---
    def action_load_and_analyze_logs(self):
        self.ensure_one()
        
        analyzer = log_analyzer.LogAnalyzer()
        self.log_file_path_display = analyzer.log_file_path or "Odoo logfile not configured or found."
        self.log_display_content = f"Loading logs from: {self.log_file_path_display}...\n"
        self.log_diagnostic_hints = "Analyzing..."
        self.log_analysis_status = 'not_run' # Temp status

        if not analyzer.log_file_path:
            self.log_analysis_status = 'no_log_file'
            self.log_display_content = "Odoo logfile path ('logfile') is not configured in odoo.conf. Cannot read logs from file."
            self.log_diagnostic_hints = "Configure 'logfile' in odoo.conf to enable this feature."
            return

        try:
            lines_to_fetch = self.log_lines_to_fetch if self.log_lines_to_fetch > 0 else 200 # Ensure positive
            
            log_lines, status_key = analyzer.get_filtered_log_lines(
                num_lines=lines_to_fetch,
                level_filter=self.log_level_filter if self.log_level_filter != 'ALL' else None,
                keyword_filter=self.log_keyword_filter or None
            )
            
            self.log_analysis_status = status_key # 'success', 'no_log_file', 'error_reading', 'empty_after_filter'
            
            if status_key == 'success':
                self.log_display_content = "\n".join(log_lines) if log_lines else "No log entries found (or file is empty)."
                if log_lines:
                    diagnostic_hints = analyzer.diagnose_logs(log_lines)
                    self.log_diagnostic_hints = "\n".join(diagnostic_hints) if diagnostic_hints else "No specific common issues diagnosed from the current log view."
                else:
                    self.log_diagnostic_hints = "Log view is empty."
            elif status_key == 'empty_after_filter':
                self.log_display_content = "No log entries found matching the current filter criteria."
                self.log_diagnostic_hints = "Try adjusting filters or increasing lines to fetch."
            else: # 'no_log_file' or 'error_reading'
                self.log_display_content = "\n".join(log_lines) # This will contain the error message from analyzer
                self.log_diagnostic_hints = "Review the error message above regarding log file access."

        except Exception as e:
            _logger.error("Error during log analysis action: %s", e, exc_info=True)
            self.log_display_content = f"An unexpected error occurred while analyzing logs: {str(e)}"
            self.log_diagnostic_hints = "Check Odoo server logs for more details."
            self.log_analysis_status = 'error_reading'
            
    # --- Run All Scans (Not installations) ---
    def action_run_all_scans(self):
        self.ensure_one()
        self.general_message = "Performing all environment scans (excluding installations and log analysis)..."
        self._format_dependency_results()
        self._format_db_check_results()
        self._format_odoo_conf_results()
        
        try:
            addon_checker = addon_requirements_checker.AddonRequirementsChecker()
            analysis = addon_checker.analyze_dependencies()
            to_install_specs_all_scan = [item['package_spec'] for item in analysis.get('to_install', [])]
            self._update_addon_req_ui_fields(
                scan_summary_lines=analysis.get('summary_lines', ['Scan completed with no summary.']),
                packages_to_install_str=";;;".join(to_install_specs_all_scan) if to_install_specs_all_scan else "",
                status='scanned_issues' if to_install_specs_all_scan else ('scanned_error' if analysis.get('errors') else 'scanned_ok')
            )
            if self.addon_req_status == 'scanned_issues':
                 self.addon_req_scan_results += "\n\n(Run All Scans found missing addon Python dependencies. Go to 'Addon Python Deps' tab to install.)"
        except Exception as e:
            _logger.error(f"Error during 'Run All Scans' for addon dependencies: {e}", exc_info=True)
            self._update_addon_req_ui_fields(scan_summary_lines=[f"Error during addon dependency scan: {e}"], status='scanned_error')

        self.general_message = "All environment scans completed. Review individual tabs. Log analysis is a manual action on its respective tab."

    # --- GitHub Integration Actions ---
    def action_update_github_repos_and_restart(self):
        """ Clones or pulls selected/active GitHub repositories and restarts Odoo. """
        self.ensure_one()
        repos_to_update = self.github_repo_ids if self.github_repo_ids else self.env['setup.assist.github.repo'].search([('active', '=', True)])

        if not repos_to_update:
            self.general_message = _("No GitHub repositories selected or marked as Active to update.")
            return

        self.general_message = _(f"Starting update process for {len(repos_to_update)} GitHub repository(s)...\n")
        all_success = True
        log_messages = []

        for repo in repos_to_update:
            log_messages.append(f"\n--- Updating Repository: {repo.name} ({repo.repo_url}@{repo.branch}) ---")
            success, message = repo.action_clone_or_pull()
            log_messages.append(f"Status: {repo.last_git_status}")
            log_messages.append(f"Log:\n{repo.last_git_log}")
            if not success:
                all_success = False
                log_messages.append(_("\n!!! Git operation failed. Skipping Odoo restart for now."))

        self.general_message += "\n".join(log_messages)

        if all_success:
            self.general_message += _("\n\nAll selected/active repositories updated successfully. Proceeding to restart Odoo service...")
            # Call the existing restart action
            restart_result = self.action_restart_odoo_service()
            # The action_restart_odoo_service already updates general_message,
            # but we can append the git status for clarity.
            # Re-fetching the record might be necessary if action_restart_odoo_service commits changes
            self.env.cache.invalidate()
            updated_self = self.browse(self.id) # Re-fetch
            updated_self.general_message = self.general_message + "\n\n-- Odoo Restart Status --\n" + updated_self.general_message

    def action_restart_odoo_service(self):
        """Restart the Odoo service. Placeholder for actual restart logic."""
        self.ensure_one()
        # You can implement actual restart logic here, e.g., call a shell command or use a helper model
        self.general_message = _("Odoo service restart requested (placeholder). If you want to implement actual restart logic, add it here.")
        return None

    def _compute_system_info(self):
        for rec in self:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.5)
                mem = psutil.virtual_memory()
                disk = shutil.disk_usage("/")
                uptime = os.popen('uptime -p').read().strip() if hasattr(os, 'popen') else "N/A"
                rec.system_info = (
                    f"OS: {platform.system()} {platform.release()}\n"
                    f"CPU Usage: {cpu_percent}%\n"
                    f"Memory: {mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB ({mem.percent}%)\n"
                    f"Disk: {disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB\n"
                    f"Uptime: {uptime}\n"
                    f"Python: {platform.python_version()}\n"
                    f"Odoo: {getattr(odoo_release, 'version', 'N/A')}\n"
                )
                rec.system_cpu_percent = cpu_percent
                rec.system_mem_percent = mem.percent
                rec.system_mem_total = f"{mem.total // (1024**2)} MB"
                rec.system_mem_used = f"{mem.used // (1024**2)} MB"
                rec.system_disk_percent = (disk.used / disk.total) * 100 if disk.total else 0
                rec.system_disk_total = f"{disk.total // (1024**3)} GB"
                rec.system_disk_used = f"{disk.used // (1024**3)} GB"
                rec.system_uptime = uptime
                rec.system_os = f"{platform.system()} {platform.release()}"
                rec.system_python = platform.python_version()
                rec.system_odoo = getattr(odoo_release, 'version', 'N/A')
                # For chart.js or similar
                rec.system_graph_data = json.dumps({
                    'cpu': cpu_percent,
                    'mem': mem.percent,
                    'disk': rec.system_disk_percent,
                })
            except Exception as e:
                rec.system_info = f"Error fetching system info: {e}"
                rec.system_graph_data = json.dumps({'cpu': 0, 'mem': 0, 'disk': 0})

    def action_scan_system_info(self):
        """Trigger recomputation of system information fields."""
        self.ensure_one()
        # The fields are computed, so we can just force recompute
        self._compute_system_info()
        self.general_message = _("System information scan completed.")