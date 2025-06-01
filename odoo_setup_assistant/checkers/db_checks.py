# -*- coding: utf-8 -*-
from odoo.tools import config as odoo_config # Access to odoo.conf parameters
import psycopg2
import logging

_logger = logging.getLogger(__name__)

class DatabaseChecker:
    """
    Checks database connectivity and basic configuration based on odoo.conf.
    """
    def __init__(self, env=None): # env can be None if called from CLI context without full Odoo env
        self.env = env
        self.messages = []
        self.status = 'ok' # Overall status: 'ok', 'warning', 'issues'

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

    def check_config_parameters(self):
        self._add_message("Checking database configuration parameters from odoo.conf...", level="info")
        required_params = {
            'db_host': {'default': 'localhost'},
            'db_port': {'default': 5432},
            'db_user': {'default': None}, 
            'db_password': {'default': None, 'sensitive': True},
        }
        
        found_all_critical = True
        for param, info in required_params.items():
            # Use odoo_config.get which correctly handles boolean False vs missing
            value = odoo_config.options.get(param) if odoo_config.options else None
            
            if value is None and 'default' in info: # Parameter not set, use default if available
                value = info['default']
                # Don't log default if it's None itself
                if value is not None:
                     self._add_message(f"Parameter '{param}' not set, using default: {value}")


            display_value = value
            
            if param == 'db_user' and not value: # Specifically check if db_user is empty or None
                self._add_message(f"'{param}' is not set or is empty in odoo.conf. This is critical.", is_issue=True)
                found_all_critical = False
                continue

            if info.get('sensitive') and value:
                display_value = "********"
            
            if value is not None:
                 self._add_message(f"Parameter '{param}': {display_value}")
            else: # Parameter not found and no default (should be caught by db_user check if critical)
                self._add_message(f"Parameter '{param}' is not set in odoo.conf.", is_warning=True if param != 'db_user' else False)


        db_name_conf = odoo_config.options.get('db_name') if odoo_config.options else None
        if db_name_conf:
            self._add_message(f"Parameter 'db_name': {db_name_conf}")
        else:
            self._add_message("Parameter 'db_name' is not set in odoo.conf. Odoo will likely show the database manager page or use dbfilter.", level="info")

        if not found_all_critical:
            self._add_message("One or more critical database parameters (like db_user) are missing or empty in odoo.conf.", is_issue=True)
        return found_all_critical

    def check_postgresql_connection(self):
        self._add_message("\nAttempting direct PostgreSQL server connection (using 'postgres' or 'template1' DB)...", level="info")
        db_host = odoo_config.options.get('db_host', 'localhost')
        db_port = odoo_config.options.get('db_port', 5432)
        db_user = odoo_config.options.get('db_user')
        db_password = odoo_config.options.get('db_password', '')

        if not db_user:
            self._add_message("`db_user` not configured. Cannot perform direct PostgreSQL connection test.", is_issue=True)
            return False

        connect_dbs = ['postgres', 'template1']
        connected_successfully = False

        for db_to_try in connect_dbs:
            try:
                self._add_message(f"Trying to connect to host: {db_host}, port: {db_port}, user: {db_user}, database: '{db_to_try}'...")
                conn = psycopg2.connect(
                    host=str(db_host),
                    port=int(db_port),
                    user=str(db_user),
                    password=str(db_password),
                    database=db_to_try,
                    connect_timeout=5
                )
                conn.close()
                self._add_message(f"Successfully connected to PostgreSQL server ({db_host}:{db_port}) as user '{db_user}' using database '{db_to_try}'.")
                connected_successfully = True
                break 
            except psycopg2.OperationalError as e:
                error_message = str(e).strip().replace('\n', ' ')
                self._add_message(f"Failed to connect using database '{db_to_try}': {error_message}", level="warning" if db_to_try == connect_dbs[-1] and not connected_successfully else "info")
                if "password authentication failed" in error_message and not connected_successfully:
                    self._add_message("Hint: Check 'db_user' and 'db_password' in odoo.conf.", is_warning=True)
                elif "Connection refused" in error_message and not connected_successfully:
                    self._add_message(f"Hint: Is PostgreSQL server running on {db_host} and listening on port {db_port}? Check firewall.", is_warning=True)
            except Exception as e:
                self._add_message(f"Unexpected error connecting with database '{db_to_try}': {str(e).strip().replace(chr(10), ' ')}", level="warning" if db_to_try == connect_dbs[-1] and not connected_successfully else "info")
        
        if not connected_successfully:
            self._add_message("Failed to establish a direct connection to the PostgreSQL server with current credentials using standard databases ('postgres', 'template1').", is_issue=True)
        return connected_successfully

    def check_odoo_current_db_connection(self):
        self._add_message("\nChecking Odoo's current database connection...", level="info")
        if not self.env:
            self._add_message("Odoo environment (database cursor) not available for this specific check. This check is usually run from within a fully loaded Odoo instance.", is_warning=True)
            return False
        
        try:
            current_db_name = self.env.cr.dbname
            self._add_message(f"Odoo reports being connected to database: '{current_db_name}'.")
            
            self.env.cr.execute("SELECT version();")
            pg_version = self.env.cr.fetchone()
            self._add_message(f"Successfully executed a test query on '{current_db_name}'. PostgreSQL Version: {pg_version[0] if pg_version else 'N/A'}")
            return True
        except Exception as e:
            self._add_message(f"Failed to verify Odoo's current database connection or execute test query: {str(e)}", is_issue=True)
            return False

    def perform_all_db_checks(self):
        self.messages = [] 
        self.status = 'ok' 

        self.check_config_parameters()
        self.check_postgresql_connection()
        if self.env: # Only run if Odoo environment is available
            self.check_odoo_current_db_connection()
        
        if not self.messages:
            self.messages.append("No database checks were performed or yielded results.")
            self.status = 'warning'
            
        return self.messages, self.status