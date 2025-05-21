import json
import time
from datetime import datetime
import numpy as np
import rasterio
from rasterio.transform import xy
import heapq
import math
import os

# Configs
COST_GRID_PATH = "data/processed/cost_grid.npy"
ELEVATION_TIF = "data/raw/elevation.tif"
DELIVERY_PATH = "data/raw/delivery_coords.json"
HUB_PATH = "data/raw/central_hub.json"


def load_barn():
    with open("data/raw/barn.json") as f:
        return json.load(f)["drones"]
# Load delivery coordinates
def load_coordinates():
    if os.stat(HUB_PATH).st_size == 0:
        raise ValueError("central_hub.json is empty!")
    if os.stat(DELIVERY_PATH).st_size == 0:
        raise ValueError("delivery_coords.json is empty!")
    with open(DELIVERY_PATH) as f:
        deliveries = json.load(f)["deliveries"]
    with open(HUB_PATH) as f:
        hub = json.load(f)
    print(hub, deliveries)
    return hub, deliveries

# Heuristic for A*
def heuristic(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

# A* algorithm
# NOTE: This implementation assumes a fixed route order (hub → pickup → drop-off → hub).
# It does not attempt to reorder waypoints or optimize multi-stop delivery sequences.
# That would be a form of the NP-hard Traveling Salesman Problem (TSP) and is out of scope for now.
def astar(grid, start, goal):
    open_heap = []
    heapq.heappush(open_heap, (0 + heuristic(start, goal), start))
    came_from = {}
    gscore = {start: 0}
    fscore = {start: heuristic(start, goal)}
    visited = np.zeros_like(grid, dtype=bool)

    while open_heap:
        current = heapq.heappop(open_heap)[1]
        if visited[current[0], current[1]]:
            continue
        visited[current[0], current[1]] = True
        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start)
            path.reverse()
            return path, gscore[goal]

        for i, j in [(-1,0), (1,0), (0,-1), (0,1), (-1,-1), (-1,1), (1,-1), (1,1)]:
            neighbor = (current[0]+i, current[1]+j)
            if 0 <= neighbor[0] < grid.shape[0] and 0 <= neighbor[1] < grid.shape[1]:
                if grid[neighbor[0], neighbor[1]] >= 100:
                    continue
                move_cost = grid[neighbor[0], neighbor[1]] * (1.414 if i != 0 and j != 0 else 1)
                tentative_g = gscore[current] + move_cost
                if tentative_g < gscore.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    gscore[neighbor] = tentative_g
                    fscore[neighbor] = tentative_g + heuristic(neighbor, goal)
                    heapq.heappush(open_heap, (fscore[neighbor], neighbor))
    return None, float('inf')

# Compute stats per leg
def simulate_leg(grid, transform, src, origin, dest, leg_number, drone_id, speed_mps):
    start_rc = src.index(origin["lon"], origin["lat"])
    goal_rc = src.index(dest["lon"], dest["lat"])
    path, cost = astar(grid, start_rc, goal_rc)
    if not path:
        raise RuntimeError("No path found")

    # Save path to file for visualization later
    os.makedirs("data/logs", exist_ok=True)
    path_file = f"data/logs/{drone_id}_leg{leg_number}_path.json"
    with open(path_file, "w") as f:
        json.dump({"path": path, "transform": transform.to_gdal()}, f)

    distance = heuristic(start_rc, goal_rc) * src.res[0]  # Grid distance * resolution
    est_time = distance / speed_mps
    timestamp = datetime.utcnow().isoformat()

    return f"""
    INSERT INTO drone_delivery.logs (
        drone_id, leg_number, origin, destination, path_cost, path_distance, estimated_time_sec, timestamp
    ) VALUES (
        '{drone_id}', {leg_number}, '{origin['name']}', '{dest['name']}',
        {cost:.2f}, {distance:.2f}, {est_time:.2f}, TIMESTAMP '{timestamp}'
    );"""


# Main simulation
if __name__ == "__main__":
    grid = np.load(COST_GRID_PATH)
    with rasterio.open(ELEVATION_TIF) as src:
        transform = src.transform
        hub, deliveries = load_coordinates()
        drones = load_barn()
        for delivery, drone in zip(deliveries, drones):
            drone_id = drone["id"]
            speed = drone["speed_mps"]
            inserts = []
            inserts.append(simulate_leg(grid, transform, src, hub, delivery["pickup"], 1, drone_id, speed))
            inserts.append(simulate_leg(grid, transform, src, delivery["pickup"], delivery["dropoff"], 2, drone_id, speed))
            inserts.append(simulate_leg(grid, transform, src, delivery["dropoff"], hub, 3, drone_id, speed))
            print("\n".join(inserts))
            print("-- End of delivery simulation --\n")


