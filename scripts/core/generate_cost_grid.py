import rasterio
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import sobel
import os

# Load elevation GeoTIFF
with rasterio.open("data/raw/elevation.tif") as src:
    elevation = src.read(1)  # Read first band
    transform = src.transform

# Optional: mask out invalid values
elevation = np.where(elevation == src.nodata, np.nan, elevation)

# Compute slope from elevation
dx = sobel(elevation, axis=1, mode='nearest')
dy = sobel(elevation, axis=0, mode='nearest')
slope = np.hypot(dx, dy)

# Normalize and scale slope to get cost
slope = np.nan_to_num(slope, nan=0.0)
cost_grid = 1 + (slope / np.max(slope)) * 9  # Cost from 1 (flat) to 10 (steep)


# Save processed cost grid
os.makedirs("data/processed", exist_ok=True)
np.save("data/processed/cost_grid.npy", cost_grid)

print("✅ Cost grid generated and saved to /data/processed/cost_grid.npy")
plt.imshow(cost_grid, cmap='hot')
plt.colorbar(label='Movement Cost')
plt.title("Movement Cost Grid (from Slope)")
plt.show()