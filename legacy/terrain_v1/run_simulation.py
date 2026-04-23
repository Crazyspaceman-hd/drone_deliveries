# run_simulation.py

# Step 1: Generate a delivery request file
from scripts.core.generate_delivery_requests import save_delivery_request

# actually write the file!
save_delivery_request()  

# Step 2: Simulate the drone delivery
import scripts.core.multi_drone_simulation

