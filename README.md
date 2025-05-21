
# 🛰️ Drone Delivery Pathfinding Simulator

A modular Python-based simulator for drone delivery routing using real-world terrain data and elevation-informed cost modeling. Built for scalability, cloud integration, and future analytical dashboards.

---

## 🚀 Project Overview

This project simulates autonomous drone deliveries through real-world terrain using elevation data and slope-based movement costs. The current focus is on the Portland, Oregon metro area, with a flexible architecture designed to scale across geographies and delivery models.

---

## 🗺️ Current Features

- 📦 **Multi-leg delivery simulation**:
  - From a central hub → pickup location → customer drop-off → return to hub

- 🌄 **Real elevation data** using USGS
- 🧠 **A\* pathfinding** algorithm with slope-based cost weighting
- 📈 **Detailed journey metrics**: cost, distance, time per leg
- 🐍 Fully Python-native (no proprietary tools)
- 🎞️ **Animated visualizations** of drone paths using `matplotlib`

---

## 🧱 Project Structure

```
data/ \
├── raw/\
│   ├── elevation.tif            
│   ├── central_hub.json         
│   └── delivery_points.json     
├── processed/
│   └── cost_grid.npy            
├── logs/
│   └── pathfinding_log.json     
```
```
src/
├── download\_data.py
├── generate\_cost\_grid.pygrid
└── pathfinder.py               

````

---

## ⚙️ Planned Features

- 🧑‍🤝‍🧑 Customer + store modeling with persistent storage
- 🐝 Multiple drones with parallel delivery simulation
- 🕒 Realistic time modeling (drone speed, delivery delay)
- ☁️ Cloud-native deployment (Trino/Iceberg, S3, Snowflake)
- 📊 Dashboard-ready metrics (efficiency, utilization, performance)
- 🔄 Airflow integration for full pipeline orchestration

---

## 💻 Getting Started

1. Clone the repo
2. Install dependencies:
   `pip install -r requirements.txt`
3. Run the pipeline:

   ```bash
   python download_data.py
   python generate_cost_grid.py
   python pathfinder.py
   ```

---

## 📌 Notes

* This repo is in **active development**.
* Elevation and delivery data are currently **mocked for Portland**.
* Contributions welcome once project stabilizes.

### ⚠️ Pathfinding Scope Note
    This simulation uses A* pathfinding between fixed points in a predetermined sequence:
    central hub → pickup → drop-off → return to hub.

    It does not attempt to reorder delivery stops or compute optimal multi-point routing.
    That kind of logic falls into the category of the Traveling Salesman Problem (TSP), which is NP-hard and out of scope for this project’s current goals.

---

## 🧠 Credits

* Elevation data: USGS
* Pathfinding: Custom implementation of A\* with diagonal and terrain cost

