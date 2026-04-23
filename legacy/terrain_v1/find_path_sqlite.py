import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import time
from datetime import datetime
import numpy as np
import rasterio
from rasterio.transform import xy
import heapq
import math
from core.delivery_logger import insert_delivery_leg
from config.trino_config import TRINO_CONFIG
from order_manager import fetch_pending_orders, mark_order_delivered

# Configs
COST_GRID_PATH = "data/processed/cost_grid.npy"
ELEVATION_TIF = "data/raw/elevation.tif"
HUB_PATH = "data/raw/central_hub.json"

def load_barn():
    with open("data/raw/barn.json") as f:
        return json.load(f)["drones"]

def load_hub():
    if os.stat(HUB_PATH).st_size == 0:
        raise ValueError("central_hub.json is empty!")
    with open(HUB_PATH) as f:
        return json.load(f)

# Heuristic for A*
def heuristic(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

# A* algorithm
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

    os.makedirs("data/logs", exist_ok=True)
    path_file = f"data/logs/{drone_id}_leg{leg_number}_path.json"
    with open(path_file, "w") as f:
        json.dump({"path": path, "transform": transform.to_gdal()}, f)

    distance = heuristic(start_rc, goal_rc) * src.res[0]
    est_time = distance / speed_mps
    timestamp = datetime.utcnow().isoformat()

    insert_delivery_leg(
        drone_id=str(drone_id),
        leg_type=f"leg{leg_number}",
        start_lat=float(origin["lat"]),
        start_lon=float(origin["lon"]),
        end_lat=float(dest["lat"]),
        end_lon=float(dest["lon"]),
        cost=float(cost),
        path_length=int(len(path)),
        duration_seconds=float(est_time)
        )

# Main simulation
if __name__ == "__main__":
    grid = np.load(COST_GRID_PATH)
    with rasterio.open(ELEVATION_TIF) as src:
        transform = src.transform
        hub = load_hub()
        drones = load_barn()

        pending_orders = fetch_pending_orders()
        deliveries = [{
            "order_id": o[0],
            "pickup": {"lat": o[3], "lon": o[4], "name": o[2]},
            "dropoff": {"lat": o[5], "lon": o[6], "name": o[1]}
        } for o in pending_orders]

        for delivery, drone in zip(deliveries, drones):
            drone_id = drone["id"]
            speed = drone["speed_mps"]
            simulate_leg(grid, transform, src, hub, delivery["pickup"], 1, drone_id, speed)
            simulate_leg(grid, transform, src, delivery["pickup"], delivery["dropoff"], 2, drone_id, speed)
            simulate_leg(grid, transform, src, delivery["dropoff"], hub, 3, drone_id, speed)
            mark_order_delivered(delivery["order_id"])
            print("-- End of delivery simulation --\n")
