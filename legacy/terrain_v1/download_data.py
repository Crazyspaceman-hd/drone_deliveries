import os
import numpy as np
import rasterio
from rasterio.transform import from_origin
import srtm

def ensure_directories():
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

def generate_srtm_dem_from_bounds(min_lat, max_lat, min_lon, max_lon, resolution=0.001):
    elevation_data = srtm.get_data()

    lats = np.arange(min_lat, max_lat + resolution, resolution)
    lons = np.arange(min_lon, max_lon + resolution, resolution)
    data = np.zeros((len(lats), len(lons)), dtype=np.float32)

    for i, lat_val in enumerate(lats):
        for j, lon_val in enumerate(lons):
            elev = elevation_data.get_elevation(lat_val, lon_val)
            data[i, j] = elev if elev is not None else -9999

    transform = from_origin(
        west=min(lons),
        north=max(lats),
        xsize=resolution,
        ysize=resolution
    )

    out_path = f"data/raw/elevation.tif"
    data = np.flipud(data)
    with rasterio.open(
        out_path,
        'w',
        driver='GTiff',
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype='float32',
        crs='EPSG:4326',
        transform=transform,
        nodata=-9999
    ) as dst:
        dst.write(data, 1)

    print(f"✅ DEM written to: {out_path}")
    return out_path


def main():
    ensure_directories()
# hard coded home depot on washington, st to random house in pleasent valley
# eventually this will be replaced with a function that takes in a start and end point
    start_lat, start_lon = 45.516487, -122.55967
    goal_lat, goal_lon   = 45.476335, -122.49055

    min_lat = min(start_lat, goal_lat)
    max_lat = max(start_lat, goal_lat)
    min_lon = min(start_lon, goal_lon)
    max_lon = max(start_lon, goal_lon)

    generate_srtm_dem_from_bounds(min_lat, max_lat, min_lon, max_lon)

if __name__ == "__main__":
    main()