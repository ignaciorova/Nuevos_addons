# -*- coding: utf-8 -*-
import configparser
from odoo.tools import config as odoo_config
import os
import logging
import re

_logger = logging.getLogger(__name__)

class OdooConfigChecker:
    def __init__(self, conf_file_path=None):
        self.messages = []
        self.status = 'ok' # ok, warning, issues
        self.config_source = "Odoo's active configuration"
        self.raw_config = {} # Stores config as read by configparser for more detailed checks
        
        # If conf_file_path is provided (CLI usage), parse it.
        # Otherwise, use odoo_config.options (Wizard usage).
        if conf_file_path:
            self.config_source = f"file: {conf_file_path}"
            self.parser = configparser.ConfigParser(interpolation=None) # No interpolation for conf files
            try:
                if not os.path.exists(conf_file_path):
                    self._add_message(f"Configuration file not found at: {conf_file_path}", is_issue=True)
                    # Store the config from odoo_config.options as a fallback if file fails but we need some config
                    self.current_odoo_options = dict(odoo_config.options) if odoo_config.options else {}
                    return 
                
                # Read file and store all sections
                self.parser.read(conf_file_path)
                if 'options' in self.parser:
                    self.current_odoo_options = dict(self.parser['options'])
                else: # If no [options] section, try to use odoo_config as fallback
                    self._add_message(f"'[options]' section not found in {conf_file_path}. Some checks might be limited.", is_warning=True)
                    self.current_odoo_options = dict(odoo_config.options) if odoo_config.options else {}
                
                # For raw_config, store all key-value pairs from all sections for detailed checks
                for section in self.parser.sections():
                    for key, value in self.parser.items(section):
                        self.raw_config[key] = value # Simpler: just get from [options] if exists for direct value checks
                if 'options' in self.parser:
                    self.raw_config = dict(self.parser['options']) # Overwrite with just options for simplicity in checks below

            except Exception as e:
                self._add_message(f"Error parsing configuration file {conf_file_path}: {e}", is_issue=True)
                self.current_odoo_options = dict(odoo_config.options) if odoo_config.options else {}
        else: # Wizard usage
            self.current_odoo_options = dict(odoo_config.options) if odoo_config.options else {}
            # For wizard, we can't easily access the raw file for comments etc.
            # So raw_config will be same as current_odoo_options
            self.raw_config = self.current_odoo_options


    def _add_message(self, message, level="info", is_issue=False, is_warning=False):
        prefix_map = {"info": "✅ INFO: ", "warning": "⚠️ WARNING: ", "error": "🔴 ERROR: "}
        final_prefix = prefix_map.get(level, "➡️ ")

        if is_issue:
            final_prefix = prefix_map["error"]
            if self.status != 'issues': self.status = 'issues'
        elif is_warning:
            final_prefix = prefix_map["warning"]
            if self.status == 'ok': self.status = 'warning'
        
        self.messages.append(f"{final_prefix}{message}")

    def _get_config_value(self, key, default=None):
        """Helper to get value from parsed config or Odoo's live config."""
        return self.current_odoo_options.get(key, default)


    def check_paths(self):
        self._add_message("Checking critical file paths...", level="info")
        paths_to_check = ['addons_path', 'data_dir']
        for path_key in paths_to_check:
            path_value_str = self._get_config_value(path_key)
            if not path_value_str:
                self._add_message(f"'{path_key}' is not defined in the configuration.", is_warning=True)
                continue

            if path_key == 'addons_path':
                individual_paths = path_value_str.split(',')
                all_paths_exist_for_key = True
                if not individual_paths or not any(p.strip() for p in individual_paths):
                     self._add_message(f"'{path_key}' is defined but seems empty or invalid: '{path_value_str}'", is_warning=True)
                     continue
                
                for p in individual_paths:
                    p_stripped = p.strip()
                    if not p_stripped: continue # Skip empty strings from trailing commas etc.
                    if not os.path.isabs(p_stripped):
                         self._add_message(f"Path in '{path_key}' is not absolute and might be ambiguous: '{p_stripped}'. It's better to use absolute paths.", is_warning=True)
                    if not os.path.exists(p_stripped):
                        self._add_message(f"Path specified in '{path_key}' does not exist: {p_stripped}", is_issue=True)
                        all_paths_exist_for_key = False
                    else:
                        self._add_message(f"Path in '{path_key}' exists: {p_stripped}")
                if all_paths_exist_for_key and individual_paths:
                     self._add_message(f"All specified paths in '{path_key}' verified.", level="info")
            else: # For data_dir and other single paths
                if not os.path.isabs(path_value_str):
                    self._add_message(f"Path for '{path_key}' ('{path_value_str}') is not absolute. Absolute paths are recommended.", is_warning=True)
                if not os.path.exists(path_value_str):
                    self._add_message(f"Path for '{path_key}' ('{path_value_str}') does not exist.", is_issue=True)
                elif not os.access(path_value_str, os.W_OK):
                    self._add_message(f"Path for '{path_key}' ('{path_value_str}') exists but is not writable by the Odoo user.", is_issue=True)
                else:
                    self._add_message(f"Path for '{path_key}': '{path_value_str}' exists and is writable.")


    def check_performance_settings(self):
        self._add_message("\nChecking performance-related settings...", level="info")
        workers = self._get_config_value('workers')
        if workers is not None: # Odoo default if not set is 0
            try:
                num_workers = int(workers)
                if num_workers == 0:
                    self._add_message("'workers = 0'. Multiprocessing is disabled. Suitable for development/small sites. For production, >0 is recommended.", is_warning=True)
                elif num_workers < 0:
                    self._add_message(f"'workers = {num_workers}' is invalid. Must be >= 0.", is_issue=True)
                else:
                    try:
                        cpu_cores = os.cpu_count() or 1 # Default to 1 if cannot determine
                        suggested_workers = (2 * cpu_cores) + 1
                        self._add_message(f"'workers = {num_workers}'. (System has ~{cpu_cores} CPU cores, typical production suggestion: ~{suggested_workers})")
                        if num_workers > suggested_workers * 2 and cpu_cores > 1 : # Arbitrary upper bound check
                             self._add_message(f"Number of workers ({num_workers}) seems high for {cpu_cores} cores. Monitor resource usage.", is_warning=True)
                    except NotImplementedError:
                         self._add_message(f"'workers = {num_workers}'. (Could not determine CPU cores for precise recommendation.)")
            except ValueError:
                self._add_message(f"'workers = {workers}' is not a valid integer.", is_issue=True)
        else: # Parameter not in conf file, Odoo defaults to 0
            self._add_message("'workers' is not explicitly set. Odoo defaults to 0 (multiprocessing disabled). Consider setting for production.", is_warning=True)

        limit_time_cpu = int(self._get_config_value('limit_time_cpu', 60)) # Odoo default
        limit_time_real = int(self._get_config_value('limit_time_real', 120)) # Odoo default
        self._add_message(f"'limit_time_cpu': {limit_time_cpu}s. Default request processing time limit (CPU).")
        self._add_message(f"'limit_time_real': {limit_time_real}s. Default request processing time limit (wall clock).")
        if limit_time_real <= limit_time_cpu :
            self._add_message("'limit_time_real' should generally be greater than 'limit_time_cpu'.", is_warning=True)


    def check_security_settings(self):
        self._add_message("\nChecking security-related settings...", level="info")
        admin_passwd = self.raw_config.get('admin_passwd') # Check raw config to see if it's literally 'admin'
        if not admin_passwd:
            self._add_message("'admin_passwd' (master password) is not set in the configuration file. This is a CRITICAL security risk if database management is exposed.", is_issue=True)
        elif admin_passwd == 'admin':
            self._add_message("'admin_passwd' is set to 'admin'. This is a default and insecure value. CRITICAL to change for production.", is_issue=True)
        else:
            self._add_message("'admin_passwd' is set. Ensure it is strong, unique, and stored securely.")

        # list_db default is True
        list_db_str = str(self._get_config_value('list_db', 'True')).lower()
        if list_db_str == 'true':
            self._add_message("'list_db = True'. Database list is visible on login page. For production, consider setting to 'False' and using dbfilter if you want to hide specific databases or the list entirely.", is_warning=True)
        else:
            self._add_message("'list_db = False'. Database list is hidden.")
        
        proxy_mode = str(self._get_config_value('proxy_mode', 'False')).lower()
        if proxy_mode == 'true':
            self._add_message("'proxy_mode = True'. Ensure Odoo is running behind a trusted reverse proxy that correctly sets X-Forwarded-* headers.", level="info")
        else:
            self._add_message("'proxy_mode = False'. Odoo is not expecting to be run behind a reverse proxy that modifies scheme/host headers (or not configured for it).")

    def check_common_misconfigurations(self):
        self._add_message("\nChecking for common misconfigurations/typos...", level="info")
        # Example: Check if log_level is valid
        log_levels = ['debug_rpc_vs_sql', 'debug_rpc_answer', 'debug_rpc', 'debug_sql', 'debug', 'info', 'warn', 'error', 'critical']
        # In Odoo 15+ log_level can be a comma separated list e.g. "odoo.models:INFO,odoo.sql_db:DEBUG"
        # For simplicity, we'll check the main log_level if it's a single known value.
        # A more complex check could parse module-specific levels.
        log_level_config = self._get_config_value('log_level', 'info')
        if ':' not in log_level_config and log_level_config not in log_levels: # Simple check for global log_level
             self._add_message(f"Configured 'log_level = {log_level_config}' is not a standard Odoo global log level ({', '.join(log_levels)}). May not be effective or could be a typo.", is_warning=True)
        else:
             self._add_message(f"'log_level' is set to '{log_level_config}'.")


    def perform_conf_checks(self):
        self.messages = []
        self.status = 'ok'

        if not self.current_odoo_options and not self.raw_config:
            # This case is hit if conf_file_path was bad AND odoo_config.options was empty
             self._add_message("No Odoo configuration loaded. Cannot perform checks.", is_issue=True)
             return self.messages, self.status

        self._add_message(f"Starting deep scan of Odoo configuration (Source: {self.config_source})...")
        self.check_paths()
        self.check_performance_settings()
        self.check_security_settings()
        self.check_common_misconfigurations()

        if not self.messages: # Should not happen if initial message is added
            self.messages.append("Odoo configuration checks ran but produced no specific messages.")
        return self.messages, self.status