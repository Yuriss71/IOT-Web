import os
from urllib.parse import urlparse
from typing import Dict
from dotenv import load_dotenv


load_dotenv()

BROKER_URL = os.getenv("BROKER_URL", "mqtt://broker.emqx.io:1883")
BROKER_TOPIC = os.getenv("BROKER_TOPIC", "ynov/bdx/lidl")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "database.sqlite3")
JWT_SECRET = os.getenv("JWT_SECRET", "jwt")
JWT_EXP_SECONDS = int(os.getenv("JWT_EXP_SECONDS", str(7 * 24 * 3600)))

def parse_mqtt_url(url: str) -> Dict[str, int | str]:
    parsed = urlparse(url if "://" in url else f"mqtt://{url}")
    host = parsed.hostname or "localhost"
    port = parsed.port or 1883
    
    return {"host": host, "port": port}
