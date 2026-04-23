
import os

# Define the root directory for the clean project
base_dir = "drone_delivery_project"

# Define the subdirectories to create within the base directory
subdirs = [
    "dags",
    "include/config",
    "scripts",
    "tests",
    "data/raw",
    "data/processed",
    "data/logs",
    "docs"
]

# Create each subdirectory
for subdir in subdirs:
    path = os.path.join(base_dir, subdir)
    os.makedirs(path, exist_ok=True)
    print(f"Created: {path}")
