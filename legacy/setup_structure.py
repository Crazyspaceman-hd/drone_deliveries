# import os

# folders = [
#     "data/raw",
#     "data/processed",
#     "scripts",
# ]

# for folder in folders:
#     os.makedirs(folder, exist_ok=True)
#     print(f"Created: {folder}")

# # Optionally, create placeholder files
# with open("scripts/generate_cost_grid.py", "w") as f:
#     f.write("# This script will generate a cost grid from elevation data\n")

# with open("scripts/pathfinder.py", "w") as f:
#     f.write("# This script will run the pathfinding algorithm using the cost grid\n")

# print("📁 Project structure set up.")


import os
import shutil
import argparse
import json

# Mapping of files to move (src → dest)
MOVE_MAP = {
    "find_path.py": "scripts/simulation/find_path.py",
    "find_path_sqlite.py": "scripts/simulation/find_path_sqlite.py",
    "order_manager.py": "scripts/core/order_manager.py",
    "multi_drone.py": "scripts/core/multi_drone_simulation.py",  # rename
    "First.py": "tests/test_first.py",
    "test_bed.py": "tests/test_bed.py",
    "scripts/config/trino_config.py": "config/trino_config.py",
    "utils/delivery_logger.py": "scripts/logging/delivery_logger.py",
}

UNDO_LOG = "reorg_undo_log.json"

def move_files(move_map):
    moved_files = []
    skipped = []

    for src, dest in move_map.items():
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
            moved_files.append((src, dest))
        else:
            skipped.append(src)

    with open(UNDO_LOG, "w") as f:
        json.dump(moved_files, f, indent=2)

    return moved_files, skipped

def undo_moves():
    if not os.path.exists(UNDO_LOG):
        print("❌ No undo log found.")
        return

    with open(UNDO_LOG, "r") as f:
        moved_files = json.load(f)

    for dest, src in moved_files:
        if os.path.exists(dest):
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dest, src)
            print(f"↩️ Undid: {dest} → {src}")
        else:
            print(f"⚠️ File missing for undo: {dest}")

    os.remove(UNDO_LOG)
    print("🧹 Undo complete.")

def cleanup_empty_dirs(root="."):
    for folder, _, _ in os.walk(root, topdown=False):
        if os.path.isdir(folder) and not os.listdir(folder):
            try:
                os.rmdir(folder)
                print(f"🧹 Removed empty folder: {folder}")
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--undo", action="store_true", help="Undo previous move")
    parser.add_argument("--cleanup", action="store_true", help="Remove empty folders after reorg")
    args = parser.parse_args()

    if args.undo:
        undo_moves()
        return

    moved, skipped = move_files(MOVE_MAP)

    print("\n✅ Moved files:")
    for src, dest in moved:
        print(f"  - {src} → {dest}")

    if skipped:
        print("\n⚠️ Skipped missing files:")
        for s in skipped:
            print(f"  - {s}")

    if args.cleanup:
        cleanup_empty_dirs()

if __name__ == "__main__":
    main()

