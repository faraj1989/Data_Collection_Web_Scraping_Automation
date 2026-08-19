import os
import sys
from pathlib import Path
import datetime

# ------------------------------------------------------------------
# CONFIGURATION - Ignore these folders and files to keep the output clean
# ------------------------------------------------------------------
IGNORE_DIRS = {
    '.venv', 'venv', 'env', '__pycache__', '.git', '.idea',
    '.pytest_cache', 'dist', 'build', '.mypy_cache', '.tox',
    'node_modules', '.vscode', 'logs', 'temp'
}

IGNORE_EXTENSIONS = {'.pyc', '.pyo', '.exe', '.dll', '.so', '.pdb'}


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------
def human_readable_size(size_bytes):
    """Convert bytes to KB, MB, GB etc."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def should_ignore(item: Path):
    """Check if the item should be skipped."""
    if item.name in IGNORE_DIRS:
        return True
    if item.suffix in IGNORE_EXTENSIONS:
        return True
    # Ignore hidden files/folders (starting with .)
    if item.name.startswith('.'):
        return True
    return False


# ------------------------------------------------------------------
# Main traversal function
# ------------------------------------------------------------------
def traverse_directory(root_path: Path, prefix: str = '', output_lines: list = None, is_last: bool = True):
    """Recursively build a tree structure of the project."""
    if output_lines is None:
        output_lines = []

    # Get all items, sorted, filtering ignored ones
    items = []
    try:
        for item in sorted(root_path.iterdir(), key=lambda x: x.name.lower()):
            if not should_ignore(item):
                items.append(item)
    except PermissionError:
        output_lines.append(f"{prefix}└── [ACCESS DENIED]")
        return output_lines

    # Separate folders and files
    folders = [i for i in items if i.is_dir()]
    files = [i for i in items if i.is_file()]

    # --- Print Folders First ---
    for idx, folder_path in enumerate(folders):
        is_last_item = (idx == len(folders) - 1) and (len(files) == 0)
        connector = '└── ' if is_last_item else '├── '

        # Add the folder name to the tree
        output_lines.append(f"{prefix}{connector}{folder_path.name}/")

        # Recurse into the folder
        extension = '    ' if is_last_item else '│   '
        traverse_directory(folder_path, prefix + extension, output_lines, is_last_item)

    # --- Print Files (with size) ---
    for idx, file_path in enumerate(files):
        is_last_item = (idx == len(files) - 1)
        connector = '└── ' if is_last_item else '├── '

        size_str = f" ({human_readable_size(file_path.stat().st_size)})"
        output_lines.append(f"{prefix}{connector}{file_path.name}{size_str}")

    return output_lines


# ------------------------------------------------------------------
# Script Entry Point
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Use the current working directory, or specify a path as an argument
    target_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    target_path = Path(target_dir).resolve()

    if not target_path.exists():
        print(f"❌ Error: Path does not exist -> {target_path}")
        sys.exit(1)

    print(f"📂 Scanning project at: {target_path}")
    print("⏳ Generating tree structure (ignoring venv, cache, etc.)...\n")

    # Build the output
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_content = [
        "=" * 70,
        f"📁 PROJECT STRUCTURE EXPORT",
        f"📅 Generated: {timestamp}",
        f"📍 Root Path: {target_path}",
        "=" * 70,
        "",
    ]

    # Run the traversal
    tree_lines = traverse_directory(target_path, prefix='', output_lines=[])
    output_content.extend(tree_lines)

    # Add a summary at the end
    output_content.append("")
    output_content.append("=" * 70)

    # Count files for summary (optional) - quick count of .py files shown in tree
    py_files = [line for line in tree_lines if line.endswith('.py)') or line.endswith('.py ')]
    output_content.append(f"🐍 Python scripts visible in tree: {len(py_files)}")
    output_content.append("=" * 70)

    # Write to a text file
    output_file = "project_structure.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_content))

    # Also print to console
    print('\n'.join(output_content))

    print(f"\n✅ Success! Structure exported to: {output_file}")
    print("📤 Please copy the contents of this file and send them to me.")