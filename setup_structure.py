import os

folders = [
    "data/raw",
    "data/processed",
    "scripts",
]

for folder in folders:
    os.makedirs(folder, exist_ok=True)
    print(f"Created: {folder}")

# Optionally, create placeholder files
with open("scripts/generate_cost_grid.py", "w") as f:
    f.write("# This script will generate a cost grid from elevation data\n")

with open("scripts/pathfinder.py", "w") as f:
    f.write("# This script will run the pathfinding algorithm using the cost grid\n")

print("📁 Project structure set up.")
