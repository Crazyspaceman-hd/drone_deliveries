import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import rasterio
from rasterio.transform import Affine, xy
import sys

# Usage: python visualize_path.py path_to_json elevation.tif
if len(sys.argv) != 3:
    print("Usage: python visualize_path.py <path_json> <elevation_tif>")
    sys.exit(1)

path_file = sys.argv[1]
elevation_file = sys.argv[2]

# Load path and transform
with open(path_file) as f:
    data = json.load(f)
    path = data["path"]
    transform = Affine.from_gdal(*data["transform"])

# Load elevation
with rasterio.open(elevation_file) as src:
    elevation = src.read(1)
    bounds = src.bounds

# Convert path (row, col) to real-world coords
coords = [xy(transform, row, col) for row, col in path]
x_vals, y_vals = zip(*coords)

# Plot setup
fig, ax = plt.subplots(figsize=(10, 10))
img = ax.imshow(elevation, cmap='terrain', extent=[bounds.left, bounds.right, bounds.bottom, bounds.top], origin='upper')
drone_dot, = ax.plot([], [], 'bo', markersize=8)
path_line, = ax.plot([], [], 'b-', linewidth=1)

# Zoom in a bit
x_pad = (max(x_vals) - min(x_vals)) * 0.2
y_pad = (max(y_vals) - min(y_vals)) * 0.2
ax.set_xlim(min(x_vals)-x_pad, max(x_vals)+x_pad)
ax.set_ylim(min(y_vals)-y_pad, max(y_vals)+y_pad)

# Animation functions
def init():
    drone_dot.set_data([], [])
    path_line.set_data([], [])
    return drone_dot, path_line

def update(frame):
    drone_dot.set_data(x_vals[frame], y_vals[frame])
    path_line.set_data(x_vals[:frame+1], y_vals[:frame+1])
    return drone_dot, path_line

ani = animation.FuncAnimation(fig, update, frames=len(path), init_func=init, blit=True, interval=100, repeat=False)
plt.title("Drone Delivery Path Visualization")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.colorbar(img, label="Elevation (m)")
plt.grid()
plt.show()