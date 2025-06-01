# -*- coding: utf-8 -*-
import os
import re
import logging
from odoo.tools import config as odoo_config

_logger = logging.getLogger(__name__)

# Basic Odoo log line pattern - this might need adjustments for custom log formats
# Example: 2023-10-27 10:30:00,123 12345 INFO my_db werkzeug: GET /web 200 OK
# More comprehensive:
# TIMESTAMP PID LEVEL DATABASE MODULE: MESSAGE
LOG_LINE_REGEX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG|TEST)\s+" # Added DEBUG, TEST
    r"(?P<database>[a-zA-Z0-9_?.-]*)\s+" # Handle '?' or actual db names
    r"(?P<module>[^:]+):\s+"
    r"(?P<message>.*)$"
)

# Define some basic diagnostic patterns and hints
# This list can be expanded significantly
DIAGNOSTIC_PATTERNS = [
    (re.compile(r"OperationalError: FATAL:\s+database \".*\" does not exist", re.IGNORECASE),
     "Hint: The database Odoo is trying to connect to does not exist. Verify 'db_name' in odoo.conf or ensure the database is created in PostgreSQL."),
    (re.compile(r"psycopg2\.OperationalError: FATAL:\s+password authentication failed for user", re.IGNORECASE),
     "Hint: PostgreSQL password authentication failed. Check 'db_user' and 'db_password' in odoo.conf and ensure the user has correct privileges in PostgreSQL."),
    (re.compile(r"Connection refused", re.IGNORECASE),
     "Hint: Odoo could not connect to the PostgreSQL server. Ensure PostgreSQL is running, accessible on the configured 'db_host' and 'db_port', and check firewall rules."),
    (re.compile(r"wkhtmltopdf: error", re.IGNORECASE),
     "Hint: An error occurred with wkhtmltopdf, likely during PDF report generation. Ensure wkhtmltopdf is correctly installed, in PATH, and has necessary permissions/dependencies (e.g., libXrender)."),
    (re.compile(r"Permission denied", re.IGNORECASE), # Generic, could be many things
     "Hint: 'Permission denied' error detected. This could relate to file system access (e.g., attachments, log file, addons path), database access, or other system resources. Check the full error message for context."),
    (re.compile(r"ImportError: No module named '(\w+)'", re.IGNORECASE),
     lambda match: f"Hint: Python module '{match.group(1)}' not found. This module needs to be installed in your Odoo's Python environment (e.g., using 'pip install {match.group(1)}')."),
    (re.compile(r"could not translate host name .* to address: Temporary failure in name resolution", re.IGNORECASE),
     "Hint: DNS resolution failed. The server could not resolve a hostname (e.g., for outgoing connections like SMTP or external APIs). Check DNS configuration and network connectivity."),
    (re.compile(r"bus.Bus unavailable, Bus.Notification unavailable", re.IGNORECASE),
     "Hint: Longpolling/Bus features might be unavailable. This could be due to 'workers > 0' not being set, or issues with the longpolling port (default 8072) if using a reverse proxy or firewall."),
]


class LogAnalyzer:
    def __init__(self):
        self.log_file_path = self._get_log_file_path()

    def _get_log_file_path(self):
        log_file = odoo_config.options.get('logfile')
        # Ensure it's an absolute path if specified, otherwise Odoo might make it relative to data_dir
        if log_file and not os.path.isabs(log_file) and odoo_config.options.get('data_dir'):
             # This logic for making it absolute might vary based on Odoo version's internal handling
             # For simplicity, we'll assume if it's not absolute, it might be tricky to locate reliably
             # without knowing Odoo's internal current working directory or specific data_dir logic at startup.
             # Best if 'logfile' in odoo.conf is absolute.
             _logger.warning(f"Logfile path '{log_file}' is not absolute. Full path resolution might be ambiguous.")
        return log_file

    def _efficient_tail(self, filepath, n_lines):
        """
        Efficiently gets the last n lines from a file.
        Handles potential encoding issues by trying utf-8 then latin-1.
        """
        if not filepath or not os.path.exists(filepath):
            raise FileNotFoundError(f"Log file not found at {filepath or 'path not configured'}")
        if not os.access(filepath, os.R_OK):
            raise PermissionError(f"No read permission for log file at {filepath}")

        placeholder = b'' # Placeholder for file attributes not needed by this method
        try:
            with open(filepath, 'rb') as f:
                f.seek(0, os.SEEK_END)
                end_byte = f.tell()
                if end_byte == 0:
                    return [] # Empty file

                lines_found = []
                buffer_size = 1024 * 4 # Read in 4KB chunks
                bytes_read_total = 0

                while len(lines_found) < n_lines +1  and bytes_read_total < end_byte :
                    offset = min(buffer_size, end_byte - bytes_read_total)
                    bytes_read_total += offset
                    
                    f.seek(end_byte - bytes_read_total)
                    chunk = f.read(offset)
                    
                    # Decode chunk and prepend to existing lines
                    try:
                        current_lines = chunk.decode('utf-8', errors='replace').splitlines()
                    except UnicodeDecodeError:
                        current_lines = chunk.decode('latin-1', errors='replace').splitlines() # Fallback
                    
                    # If reading from middle of file, first line of chunk might be incomplete from previous chunk
                    # And last line of previous lines_found might have been incomplete
                    if lines_found and current_lines: # If we have previous lines and current lines
                        lines_found[0] = current_lines[-1] + lines_found[0] # Prepend last part of current to first part of old
                        current_lines = current_lines[:-1] # Remove the last line as it's merged

                    lines_found = current_lines + lines_found
                
                return lines_found[-n_lines:] # Return the requested number of lines
        except Exception as e:
            _logger.error(f"Error tailing log file {filepath}: {e}")
            raise # Re-raise to be caught by the calling wizard method

    def get_filtered_log_lines(self, num_lines=200, level_filter='ALL', keyword_filter=None):
        """
        Fetches, filters, and returns log lines.
        """
        if not self.log_file_path:
            return ["Odoo log file path ('logfile') is not configured in odoo.conf."], 'no_log_file'

        try:
            raw_lines = self._efficient_tail(self.log_file_path, num_lines)
        except FileNotFoundError:
            return [f"Log file '{self.log_file_path}' not found."], 'no_log_file'
        except PermissionError:
            return [f"Permission denied when trying to read log file '{self.log_file_path}'."], 'error_reading'
        except Exception as e:
            return [f"An error occurred while reading the log file: {str(e)}"], 'error_reading'

        if not raw_lines:
            return ["Log file is empty or no lines fetched."], 'success' # Technically success, but empty

        filtered_lines = []
        for line in raw_lines:
            line_passes = True
            
            # Keyword filter (case-insensitive)
            if keyword_filter:
                if keyword_filter.lower() not in line.lower():
                    line_passes = False
            
            # Level filter (if keyword filter passed or no keyword filter)
            if line_passes and level_filter != 'ALL':
                match = LOG_LINE_REGEX.match(line)
                if match:
                    if match.group('level').upper() != level_filter.upper():
                        line_passes = False
                else: # If line doesn't match Odoo format, it won't pass specific level filters
                    if level_filter not in ['INFO', 'DEBUG']: # Only show non-matching lines for broad filters
                        line_passes = False


            if line_passes:
                filtered_lines.append(line)
        
        if not filtered_lines and raw_lines: # Lines were fetched but all filtered out
             return ["No log entries found matching the current filter criteria."], 'empty_after_filter'

        return filtered_lines, 'success'

    def diagnose_logs(self, log_lines):
        """
        Analyzes a list of log lines for known error patterns and returns diagnostic hints.
        """
        hints = []
        unique_hints = set() # To avoid duplicate hints for same pattern

        for line in log_lines:
            # Only try to diagnose lines that are likely errors or critical
            if not ("ERROR" in line or "CRITICAL" in line or "WARNING" in line): # Added WARNING
                continue

            for pattern, hint_or_func in DIAGNOSTIC_PATTERNS:
                match = pattern.search(line)
                if match:
                    hint_text = hint_or_func(match) if callable(hint_or_func) else hint_or_func
                    if hint_text not in unique_hints:
                        hints.append(f"- {hint_text} (related to log: ...{line[-150:]})") # Show part of the log
                        unique_hints.add(hint_text)
                    # break # Optional: Stop after first pattern match for a line
        
        if not hints:
            hints.append("No specific common issues automatically diagnosed from the current log view. Review logs manually for details.")
        return hints