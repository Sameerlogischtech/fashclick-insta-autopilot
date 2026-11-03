"""Loads settings from .env so every script shares one config."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.getenv("IG_USER_ID", "")
IG_APP_SECRET = os.getenv("IG_APP_SECRET", "")
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")
# New Meta apps use "Unified login" with a system-user token, which talks to
# graph.facebook.com. Older "Instagram login" apps use graph.instagram.com.
# Left empty, it's picked from the token: Instagram tokens start with "IG".
GRAPH_HOST = os.getenv("GRAPH_HOST", "") or (
    "graph.instagram.com" if IG_ACCESS_TOKEN.startswith("IG") else "graph.facebook.com")
# Which id sends DMs. Defaults to the Instagram account; set a Facebook Page id
# here if Meta answers DM calls with an "unsupported" error.
IG_MESSAGING_ID = os.getenv("IG_MESSAGING_ID", "") or IG_USER_ID

# DRY_RUN logs what would be sent to Instagram instead of sending it.
DRY_RUN = _bool("DRY_RUN")

RULES_FILE = BASE_DIR / os.getenv("RULES_FILE", "rules.json")
QUEUE_FILE = BASE_DIR / os.getenv("QUEUE_FILE", "queue.json")
STATE_FILE = BASE_DIR / os.getenv("STATE_FILE", "state.json")
ENV_FILE = BASE_DIR / ".env"
