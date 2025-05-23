import os
from dotenv import load_dotenv

load_dotenv()

TRINO_CONFIG = {
    "host": os.getenv("TRINO_HOST"),
    "port": int(os.getenv("TRINO_PORT", "443")),
    "user": os.getenv("TRINO_USER"),
    "catalog": os.getenv("TRINO_CATALOG", "iceberg"),
    "schema": os.getenv("TRINO_SCHEMA", "drone_sim"),
    "http_scheme": "https" if os.getenv("TRINO_USE_HTTPS", "true").lower() == "true" else "http",
}

# Optional password or token auth
if "TRINO_AUTH_TOKEN" in os.environ:
    from trino.auth import JWTAuthentication
    TRINO_CONFIG["auth"] = JWTAuthentication(os.getenv("TRINO_AUTH_TOKEN"))
elif "TRINO_PASSWORD" in os.environ:
    from trino.auth import BasicAuthentication
    TRINO_CONFIG["auth"] = BasicAuthentication(TRINO_CONFIG["user"], os.getenv("TRINO_PASSWORD"))
