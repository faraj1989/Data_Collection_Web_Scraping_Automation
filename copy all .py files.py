import os
import shutil

# ==========================================
# SOURCE FOLDER
# ==========================================
source_dir = r"M:\python"

# ==========================================
# DESTINATION FOLDER
# ==========================================
destination_dir = ""

# Create destination folder
os.makedirs(destination_dir, exist_ok=True)

# ==========================================
# Folders to SKIP
# ==========================================
skip_folders = {
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".git",
    "site-packages",
    "Lib",
    "Scripts",
    "Include"
}

# ==========================================
# Traverse folders
# ==========================================
for root, dirs, files in os.walk(source_dir):

    # Remove skipped folders from traversal
    dirs[:] = [d for d in dirs if d not in skip_folders]

    # Get relative path
    relative_path = os.path.relpath(root, source_dir)

    # Create same folder structure
    target_folder = os.path.join(destination_dir, relative_path)
    os.makedirs(target_folder, exist_ok=True)

    # Copy only .py files
    for file in files:

        if file.endswith(".py"):

            source_file = os.path.join(root, file)
            destination_file = os.path.join(target_folder, file)

            try:
                shutil.copy2(source_file, destination_file)
                print(f"[COPIED] {source_file}")

            except Exception as e:
                print(f"[ERROR] {source_file}")
                print(e)

print("\nDONE ✔ Only your Python files were copied.")