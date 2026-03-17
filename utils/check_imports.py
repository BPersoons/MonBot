import os
import ast
import sys

def get_python_files(directory):
    py_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                py_files.append(os.path.join(root, file))
    return py_files

def check_imports(file_path):
    missing_imports = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        
        # Simple heuristic: Check if 'json', 'time', 'requests', 'logging' are used but not imported
        # This is a basic static analysis.
        
        # Gather imports
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split('.')[0])

        # Gather usages of common standard libs that often get missed
        common_libs = {'json', 'time', 'requests', 'logging', 'os', 'datetime'}
        used_names = set()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in common_libs:
                    used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in common_libs:
                    used_names.add(node.value.id)

        for lib in used_names:
            if lib not in imported_names:
                # datetime is special case (from datetime import datetime) logic handles it poorly above
                # so strict check might be noisy. 
                # Improvement: Check if the name binds to the module.
                if lib == 'datetime' and 'datetime' in imported_names: continue
                missing_imports.append(lib)

    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []

    return missing_imports

def main():
    print("Starting Global Import Sweep...")
    base_dir = os.getcwd()
    agents_dir = os.path.join(base_dir, "agents")
    utils_dir = os.path.join(base_dir, "utils")
    
    files = get_python_files(agents_dir) + get_python_files(utils_dir)
    files.append(os.path.join(base_dir, "main.py"))

    found_issues = False
    for file in files:
        if not os.path.exists(file): continue
        missing = check_imports(file)
        if missing:
            found_issues = True
            print(f"File: {os.path.relpath(file, base_dir)}")
            print(f"  --> Potential missing imports: {', '.join(missing)}")
    
    if not found_issues:
        print("No obvious missing standard library imports found.")

if __name__ == "__main__":
    main()
