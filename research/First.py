import matplotlib.pyplot as plt
import matplotlib.animation as animation
import heapq
import numpy as np
import time
import rasterio
import json
from rasterio.transform import xy

# Convert grid into a NumPy array
grid_array = np.load("data/processed/cost_grid.npy")

with rasterio.open("data/raw/elevation.tif") as src:
    # Real-world coordinates
    start_latlon = (43.298855, -72.481819)       # Springfield Hospital
    goal_latlon = (43.443923, -72.453886)      # Mt. Ascutney Summit
    elevation = src.read(1)
    transform = src.transform

    # Convert (lat, lon) → (row, col)
    start = src.index(start_latlon[1], start_latlon[0])  # (lon, lat)
    goal = src.index(goal_latlon[1], goal_latlon[0])
    bounds = src.bounds

    print(f"Start (Springfield Hospital): {start}")
    print(f"Goal (Mt. Ascutney Summit): {goal}")

# Define start and goal points
step_size = 0.1

# Initialize position
position = list(start)
# Define neighbors for movement (4 cardinal + 4 diagonal)
neighbors = [
    (0,1), (1,0), (0,-1), (-1,0),       # Cardinal
    (1,1), (-1,-1), (-1,1), (1,-1)      # Diagonals
]
# Store path for plotting
path_x = []
path_y = []

# Function to calculate heuristic (Euclidean distance)
def heuristic(a, b):
    return ((a[0]-b[0])**2 + (a[1]-b[1])**2)**0.5

# A* algorithm with heap for pathfinding
def astar_with_heap_debug(grid, start, goal):
    open_heap = []
    gscore = {start: 0}
    fscore = {start: heuristic(start, goal)}
    visited = np.zeros_like(grid, dtype=bool)
    heapq.heappush(open_heap, (fscore[start], start))
    came_from = {}

    step = 0
    while open_heap:
        # Itterate the step count
        step += 1
        # Pop second element of the heap, first must remain
        current = heapq.heappop(open_heap)[1]
        # Check if the current node has been visited
        if visited[current[0], current[1]]:
            continue
        visited[current[0], current[1]] = True
        # Print step and heap size every 1000 iterations
        if step % 1000 == 0:
            print(f"Step {step}, Open Heap Size: {len(open_heap)}")
        # Check if the current node is the goal
        if current == goal:
            print("\nGoal Reached!")
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start)
            path.reverse()
            return {
                "path": path,
                "total_cost": gscore[goal],
                "steps_taken": step
            }
        # If current is not the goal, iterate through the neighbors
        for i, j in neighbors:
            neighbor = (current[0]+i, current[1]+j)
            if 0 <= neighbor[0] < len(grid) and 0 <= neighbor[1] < len(grid[0]):
                if grid[neighbor[0]][neighbor[1]] == 1:
                    continue

                # Code for diagonal movement cost
                is_diag = abs(i) == 1 and abs(j) == 1
                move_cost = grid[neighbor[0], neighbor[1]] * (1.414 if is_diag else 1)
                tentative_g_score = gscore[current] + move_cost
                
                if tentative_g_score < gscore.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    gscore[neighbor] = tentative_g_score
                    fscore[neighbor] = tentative_g_score + heuristic(neighbor, goal)
                    heapq.heappush(open_heap, (fscore[neighbor], neighbor))

    # If we exhaust the open heap without finding the goal
    print("\nNo Path Found.")
    return {"path": "No Path Found", "total_cost": float("inf"), "steps_taken": step, "timestamp_unix" : time.time(),}

# Function to simplify the path by removing unnecessary points
def simplify_path(path):
    if len(path) <= 2:
        # Nothing to simplify
        return path  

    simplified = [path[0]]
    direction = None

    for i in range(1, len(path)-1):
        prev = path[i-1]
        curr = path[i]
        next_ = path[i+1]

        # Calculate direction vectors
        vec1 = (curr[0] - prev[0], curr[1] - prev[1])
        vec2 = (next_[0] - curr[0], next_[1] - curr[1])

        if vec1 != vec2:
            simplified.append(curr)

    simplified.append(path[-1])
    return simplified

# Run A* algorithm to find path
start_time = time.time()
full_path=astar_with_heap_debug(grid_array, start, goal)
print(full_path)
path = simplify_path(full_path["path"]) if full_path["path"] else []
runtime = time.time() - start_time
print(f"A* runtime: {runtime:.2f} seconds")

# Save stats
stats = {
    "start": start,
    "goal": goal,
    "runtime_sec": round(runtime, 2),
    "steps_taken": full_path["steps_taken"],
    "total_cost": round(full_path["total_cost"], 2) if full_path else None,
    "path_length": len(full_path['path']) if full_path else 0,
    "timestamp_unix" : time.time(),
}
# Display stats in terminal
print("\n=== Pathfinding Stats ===")
for k, v in stats.items():
    print(f"{k}: {v}")

# Save stats to JSON file
with open("data/logs/pathfinding_log.json", "a") as f:
    f.write(json.dumps(stats) + "\n")

# Set up plot
fig, ax = plt.subplots(figsize=(10, 10))

# Real-world extent for georeferenced image
extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
img = ax.imshow(elevation, cmap='terrain', extent=extent, origin='upper')

# Convert (row, col) to (x, y) in real-world coords
start_xy = xy(transform, *start)
goal_xy = xy(transform, *goal)

ax.set_xticks(np.arange(-0.5, grid_array.shape[1], 1), minor=True)
ax.set_yticks(np.arange(-0.5, grid_array.shape[0], 1), minor=True)
ax.grid(which='minor', color='black', linestyle='-', linewidth=1)
ax.set_xticks([])
ax.set_yticks([])
ax.set_aspect('equal')
ax.plot(start_xy[0], start_xy[1], 'bo', label='Springfield Hospital (Start)')
ax.plot(goal_xy[0], goal_xy[1], 'ro', label='Mount Ascutney (Goal)')
# Drone marker
drone_dot, = ax.plot([], [], 'bo', markersize=10)  
# Trail line
path_line, = ax.plot([], [], 'b-', linewidth=1)    

# Intialize the plot
def init():
    global path_x, path_y
    path_x = [start_xy[0]]
    path_y = [start_xy[1]]
    drone_dot.set_data([start_xy[0]], [start_xy[1]])
    path_line.set_data(path_x, path_y)
    return drone_dot, path_line


# Animate the drone movement
# Update function for animation
def update(frame):
    global path, path_x, path_y
    if path:
        row, col = path.pop(0)
        x, y = xy(transform, row, col)

        path_x.append(x)
        path_y.append(y)

        drone_dot.set_data([x], [y])
        path_line.set_data(path_x, path_y)
        return drone_dot, path_line
    else:
        return drone_dot, path_line
    
# Zoom in around the start/goal points
x_coords = [start_xy[0], goal_xy[0]]
y_coords = [start_xy[1], goal_xy[1]]
x_pad = (max(x_coords) - min(x_coords)) * 0.3
y_pad = (max(y_coords) - min(y_coords)) * 0.3
ax.set_xlim(min(x_coords)-x_pad, max(x_coords)+x_pad)
ax.set_ylim(min(y_coords)-y_pad, max(y_coords)+y_pad)


ani = animation.FuncAnimation(fig, update, frames=500, init_func=init, blit=True, interval=100, repeat=False)

# Show the plot
plt.title("Elevation Map with Start and Goal")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.legend()
plt.colorbar(img, label="Elevation (m)")
plt.grid()
plt.show()