# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import logging
from odoo.tools import config as odoo_config

# Try to use importlib.metadata (Python 3.8+) falling back to pkg_resources
try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import pkg_resources # type: ignore

_logger = logging.getLogger(__name__)

# Attempt to import packaging, log if not found
try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import parse as parse_version
    PACKAGING_LIB_AVAILABLE = True
except ImportError:
    PACKAGING_LIB_AVAILABLE = False
    _logger.warning(
        "'packaging' library not found. Python package version checking will be basic. "
        "Consider installing it ('pip install packaging') for more accurate checks."
    )


class AddonRequirementsChecker:
    """
    Scans Odoo addons for requirements.txt files and can attempt to install
    missing Python dependencies.
    """
    def __init__(self):
        self.messages = [] # For general logging within the class
        self.addons_paths = self._get_addons_paths()

    def _add_message(self, message, level="info"):
        # self.messages.append(message) # Internal log, not for UI directly
        if level == "info":
            _logger.info(message)
        elif level == "warning":
            _logger.warning(message)
        elif level == "error":
            _logger.error(message)

    def _get_addons_paths(self):
        paths_str = odoo_config.get('addons_path', '')
        if not paths_str:
            self._add_message("Addons path not configured in odoo.conf.", "warning")
            return []
        return [p.strip() for p in paths_str.split(',') if p.strip()]

    def _parse_requirements_file(self, file_path):
        packages = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        packages.append(line)
        except Exception as e:
            self._add_message(f"Error reading requirements file {file_path}: {e}", "error")
        return packages

    def find_requirements(self):
        module_requirements = {}
        if not self.addons_paths:
            self._add_message("No addons paths to scan.", "warning")
            return module_requirements

        for addons_path in self.addons_paths:
            if not os.path.isdir(addons_path):
                self._add_message(f"Addons path does not exist or is not a directory: {addons_path}", "warning")
                continue
            
            try:
                for module_name in os.listdir(addons_path):
                    module_path = os.path.join(addons_path, module_name)
                    manifest_path = os.path.join(module_path, '__manifest__.py')
                    if os.path.isdir(module_path) and os.path.exists(manifest_path):
                        requirements_file_path = os.path.join(module_path, 'requirements.txt')
                        if os.path.exists(requirements_file_path):
                            packages = self._parse_requirements_file(requirements_file_path)
                            if packages:
                                module_requirements[module_name] = {
                                    'path': module_path,
                                    'requirements_file': requirements_file_path,
                                    'packages': packages
                                }
            except Exception as e:
                self._add_message(f"Error scanning addons path {addons_path}: {e}", "error")
        return module_requirements

    def _check_package_installed_basic(self, package_name_no_version):
        """Basic check if package exists, without version check (if packaging lib not found)."""
        try:
            if 'importlib_metadata' in sys.modules:
                dist = importlib_metadata.distribution(package_name_no_version)
                return True, dist.version, None # Found, version, no specific requirement
            else:
                dist = pkg_resources.get_distribution(package_name_no_version)
                return True, dist.version, None
        except (importlib_metadata.PackageNotFoundError if 'importlib_metadata' in sys.modules else pkg_resources.DistributionNotFound):
            return False, "Not installed", None
        except Exception: # Handle cases where even pkg_resources might fail for odd package names
            return False, "Error checking package", None


    def _check_package_installed_advanced(self, package_spec):
        """Checks if a single package (with optional version) is installed using packaging lib."""
        try:
            req = Requirement(package_spec)
            # Normalize the package name for lookup
            package_name_normalized = canonicalize_name(req.name)
            required_version_specifier = req.specifier # This is a SpecifierSet
        except Exception as e: # Invalid requirement string
             _logger.warning(f"Invalid package spec: {package_spec} ({e}). Treating as simple name.")
             # Basic fallback if spec is malformed, just use the spec as name and require no specific version
             package_name_normalized = canonicalize_name(package_spec.split('==')[0].split('>=')[0].split('<=')[0].split('!=')[0].split('~=')[0].split('>')[0].split('<')[0].strip())
             required_version_specifier = None


        try:
            if 'importlib_metadata' in sys.modules:
                dist = importlib_metadata.distribution(package_name_normalized)
                installed_version_str = dist.version
            else:
                dist = pkg_resources.get_distribution(package_name_normalized)
                installed_version_str = dist.version
            
            installed_version = parse_version(installed_version_str)

            if required_version_specifier: # If Requirement object parsed specifiers
                if installed_version in required_version_specifier:
                    return True, str(installed_version), str(required_version_specifier)
                else:
                    return False, f"Version conflict: Installed {installed_version}, Required {required_version_specifier}", str(required_version_specifier)
            else: # No version specified in requirements.txt or spec was malformed
                return True, str(installed_version), None
        except (importlib_metadata.PackageNotFoundError if 'importlib_metadata' in sys.modules else pkg_resources.DistributionNotFound):
            return False, "Not installed", str(required_version_specifier) if required_version_specifier else None
        except Exception as e:
            _logger.error(f"Error checking package '{package_name_normalized}' (from spec '{package_spec}'): {e}")
            return False, f"Error checking: {e}", str(required_version_specifier) if required_version_specifier else None

    def _check_package_installed(self, package_spec):
        if PACKAGING_LIB_AVAILABLE:
            return self._check_package_installed_advanced(package_spec)
        else:
            # Basic check: just extract name, ignore version specifiers
            package_name_only = package_spec.split('==')[0].split('>=')[0].split('<=')[0].split('!=')[0].split('~=')[0].split('>')[0].split('<')[0].strip()
            is_installed, status_msg, _ = self._check_package_installed_basic(package_name_only)
            if not is_installed and status_msg == "Not installed":
                return is_installed, status_msg, package_spec # Return original spec as required
            return is_installed, status_msg, None # No specific version required by this basic check


    def analyze_dependencies(self):
        module_requirements_map = self.find_requirements()
        to_install = []
        satisfied = []
        errors = [] # Errors during the check process, not pip install errors
        summary_lines = []

        if not module_requirements_map:
            summary_lines.append("No 'requirements.txt' files found in any scanned addon modules.")
            return {'to_install': [], 'satisfied': [], 'errors': [], 'summary_lines': summary_lines}

        summary_lines.append(f"Found 'requirements.txt' in {len(module_requirements_map)} module(s). Analyzing dependencies...\n")

        for module_name, details in module_requirements_map.items():
            summary_lines.append(f"Module: '{module_name}'")
            if not details['packages']:
                summary_lines.append("  - No packages listed in its requirements.txt.")
                continue

            for package_spec in details['packages']:
                is_installed, status_msg, req_ver_spec_str = self._check_package_installed(package_spec)
                actual_required_spec = req_ver_spec_str if req_ver_spec_str else "any version"
                
                if is_installed:
                    satisfied.append({'module': module_name, 'package_spec': package_spec, 'installed_version': status_msg})
                    summary_lines.append(f"  - ✅ {package_spec} (Installed: {status_msg})")
                elif "Not installed" in status_msg or "Version conflict" in status_msg :
                    to_install.append({'module': module_name, 'package_spec': package_spec, 'reason': status_msg})
                    summary_lines.append(f"  - ⚠️ {package_spec} (Required: {actual_required_spec}, Status: {status_msg}) - Marked for installation.")
                else: # Error checking package itself
                    errors.append({'module': module_name, 'package_spec': package_spec, 'error': status_msg})
                    summary_lines.append(f"  - ❌ {package_spec} (Error during check: {status_msg})")
            summary_lines.append("")

        if not to_install and not errors:
            summary_lines.append("\nAll discovered Python dependencies are satisfied.")
        elif to_install:
            summary_lines.append(f"\nFound {len(to_install)} Python package(s) that need installation or update.")
        if errors:
            summary_lines.append(f"\nEncountered {len(errors)} error(s) while checking package statuses.")
        
        return {'to_install': to_install, 'satisfied': satisfied, 'errors': errors, 'summary_lines': summary_lines}

    def install_packages(self, packages_to_install_specs):
        success = []
        failed = {}
        log_lines = []

        if not packages_to_install_specs:
            log_lines.append("No packages specified for installation.")
            return {'success': success, 'failed': failed, 'log_lines': log_lines}

        pip_executable = [sys.executable, "-m", "pip"]
        log_lines.append(f"Using pip: {' '.join(pip_executable)}")

        for package_spec in packages_to_install_specs:
            log_lines.append(f"\nAttempting to install/update: {package_spec}...")
            cmd = pip_executable + ["install", package_spec] # Add --upgrade if we want to force upgrade
            try:
                cmd_str = [str(c) for c in cmd]
                process = subprocess.Popen(cmd_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
                stdout, stderr = process.communicate(timeout=300)

                log_lines.append(f"--- PIP STDOUT for {package_spec} ---")
                log_lines.extend(stdout.splitlines())
                log_lines.append(f"--- PIP STDERR for {package_spec} ---")
                log_lines.extend(stderr.splitlines())
                log_lines.append("-----------------------------")

                if process.returncode == 0:
                    log_lines.append(f"Successfully processed {package_spec}.")
                    success.append(package_spec)
                else:
                    log_lines.append(f"Failed to process {package_spec}. PIP Return Code: {process.returncode}")
                    failed[package_spec] = f"PIP Return Code: {process.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            except subprocess.TimeoutExpired:
                log_lines.append(f"Timeout expired while trying to install {package_spec}.")
                failed[package_spec] = "Installation timed out after 5 minutes."
                if 'process' in locals() and process.poll() is None: # check if process exists and is running
                    process.kill()
                    out, err = process.communicate() 
                    log_lines.append("Killed pip process due to timeout.")
            except Exception as e:
                log_lines.append(f"An unexpected error occurred while trying to install {package_spec}: {e}")
                failed[package_spec] = str(e)
        
        return {'success': success, 'failed': failed, 'log_lines': log_lines}