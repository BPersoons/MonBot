import os
import sys
import importlib.util
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PreFlight-Imports")

def validate_imports(start_dir):
    """
    Recursively finds all Python files in the given directory and attempts to import them.
    Returns True if all imports succeed, False otherwise.
    """
    project_root = os.path.abspath(start_dir)
    sys.path.insert(0, project_root)
    
    error_count = 0
    checked_count = 0
    
    logger.info(f"Starting import validation in: {project_root}")

    # Walk through the directory structure
    for root, dirs, files in os.walk(project_root):
        # Skip hidden directories and tests
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'tests']
        
        for file in files:
            if file.endswith(".py") and file != "check_imports.py":
                file_path = os.path.join(root, file)
                module_name = os.path.relpath(file_path, project_root).replace(os.path.sep, ".")[:-3]
                
                # specific excludes
                if module_name in ["main", "adk_app", "demo_adk", "dashboard", "setup", "validate_imports"]: 
                    continue 

                try:
                    # logger.info(f"Checking: {module_name}")
                    importlib.import_module(module_name)
                    checked_count += 1
                except ImportError as e:
                    logger.error(f"❌ ImportError in {module_name}: {e}")
                    error_count += 1
                except Exception as e:
                    logger.error(f"❌ Unexpected error importing {module_name}: {e}")
                    error_count += 1

    logger.info(f"Validation complete. Checked {checked_count} modules.")
    
    if error_count > 0:
        logger.error(f"FAILED: Found {error_count} import errors.")
        return False
    else:
        logger.info("SUCCESS: All modules imported correctly.")
        return True

if __name__ == "__main__":
    # Validate specific packages to avoid side effects of top-level scripts
    # Assumes script is run from project root: python -m tests.pre_flight.check_imports
    
    project_root = os.getcwd()
    logger.info(f"Project root assumed as: {project_root}")

    packages_to_check = ['agents', 'core', 'utils', 'integrations']
    
    success_all = True
    for pkg in packages_to_check:
        pkg_path = os.path.join(project_root, pkg)
        if os.path.isdir(pkg_path):
            if not validate_imports(pkg_path):
                success_all = False
        else:
            logger.warning(f"Package directory not found: {pkg}")

    if not success_all:
        sys.exit(1)
    
    logger.info("✅ PRE-FLIGHT IMPORT CHECK PASSED")
    sys.exit(0)
