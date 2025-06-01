# -*- coding: utf-8 -*-
import importlib
import subprocess
import os
import logging

_logger = logging.getLogger(__name__)

# Python libraries commonly needed by Odoo or its modules
PYTHON_DEPENDENCIES = [
    'babel', 'ldap3', 'lxml', 'num2words', 'pillow', 'polib', 'psutil',
    'psycopg2', 'pydot', 'pyopenssl', 'pypdf2', 'pyserial', # psycopg2-binary is often used instead of psycopg2
    'python-dateutil', 'python-stdnum', 'pytz', 'qrcode',
    'reportlab', 'requests', 'vobject', 'werkzeug', 'xlrd', 'xlsxwriter',
    'zeep', # For SOAP clients, often used in Odoo integrations
    # Common image/graphics libraries beyond Pillow
    'freezegun', # For testing date/time
    'passlib', # For password hashing
    'ofxparse', # For OFX bank statement imports
    # Add more as needed based on common community modules or core Odoo features.
]

# System dependencies (name and how to check if it's typically available)
SYSTEM_DEPENDENCIES = {
    'wkhtmltopdf': {'check_command': ['which', 'wkhtmltopdf'], 'hint': 'PDF Report generation (e.g., invoices, sales orders)'},
    'psql': {'check_command': ['which', 'psql'], 'hint': 'PostgreSQL client utilities (useful for DB management/debug)'},
    'node': {'check_command': ['which', 'node'], 'hint': 'JavaScript runtime (for assets build process, optional for running if assets pre-built)'},
    'npm': {'check_command': ['which', 'npm'], 'hint': 'Node Package Manager (for assets build process, often with node)'},
    'lessc': {'check_command': ['which', 'lessc'], 'hint': 'LESS CSS pre-processor (for assets build, often installed via npm)'},
    'pg_dump': {'check_command': ['which', 'pg_dump'], 'hint': 'PostgreSQL database backup utility'},
    'pg_restore': {'check_command': ['which', 'pg_restore'], 'hint': 'PostgreSQL database restore utility'},
}

class DependencyChecker:
    """
    Checks for necessary Python and system dependencies.
    """
    def __init__(self):
        self.missing_python_libs = []
        self.found_python_libs = []
        self.missing_system_deps = []
        self.found_system_deps = []

    def check_python_libraries(self):
        _logger.info("Starting Python library check...")
        self.missing_python_libs = []
        self.found_python_libs = []
        for lib_name in PYTHON_DEPENDENCIES:
            try:
                # For psycopg2, common to use psycopg2-binary
                if lib_name == 'psycopg2':
                    try:
                        importlib.import_module('psycopg2')
                    except ImportError:
                        importlib.import_module('psycopg2cffi') # Alternative often used
                        lib_name = 'psycopg2 (via psycopg2cffi)' # Indicate if found via cffi
                    # No need to check for psycopg2-binary explicitly here,
                    # as just `import psycopg2` works if binary is installed.
                else:
                    importlib.import_module(lib_name)
                
                self.found_python_libs.append(lib_name)
                _logger.debug(f"Python library found: {lib_name}")
            except ImportError:
                self.missing_python_libs.append(lib_name)
                _logger.warning(f"Python library missing: {lib_name}")
        _logger.info("Python library check finished.")
        return self.missing_python_libs, self.found_python_libs

    def check_system_dependencies(self):
        _logger.info("Starting system dependency check...")
        self.missing_system_deps = []
        self.found_system_deps = []
        for dep_name, dep_info in SYSTEM_DEPENDENCIES.items():
            try:
                process = subprocess.Popen(dep_info['check_command'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(timeout=5) # 5 sec timeout
                if process.returncode == 0 and stdout:
                    self.found_system_deps.append({'name': dep_name, 'path': stdout.strip(), 'hint': dep_info.get('hint','')})
                    _logger.debug(f"System dependency found: {dep_name} at {stdout.strip()}")
                else:
                    self.missing_system_deps.append({'name': dep_name, 'hint': dep_info.get('hint','')})
                    _logger.warning(f"System dependency missing: {dep_name}. STDOUT: {stdout.strip()}, STDERR: {stderr.strip()}")
            except FileNotFoundError: # If 'which' itself is not found or the command
                self.missing_system_deps.append({'name': dep_name, 'hint': dep_info.get('hint','')})
                _logger.warning(f"System dependency check command not found for: {dep_name} (Command: {' '.join(dep_info['check_command'])})")
            except subprocess.TimeoutExpired:
                self.missing_system_deps.append({'name': dep_name, 'hint': dep_info.get('hint','')})
                _logger.warning(f"Timeout checking system dependency: {dep_name}")
            except Exception as e:
                self.missing_system_deps.append({'name': dep_name, 'hint': dep_info.get('hint','')})
                _logger.error(f"Error checking system dependency {dep_name}: {e}")
        _logger.info("System dependency check finished.")
        return self.missing_system_deps, self.found_system_deps

    def get_all_dependency_statuses(self):
        missing_py, found_py = self.check_python_libraries()
        missing_sys, found_sys = self.check_system_dependencies()
        
        return {
            "python": {
                "missing": missing_py,
                "found": found_py,
                "status": "OK" if not missing_py else "ISSUES"
            },
            "system": {
                "missing": missing_sys,
                "found": found_sys,
                "status": "OK" if not missing_sys else "ISSUES"
            }
        }
    