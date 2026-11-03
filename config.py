"""Loads settings from .env so every script shares one config.

Several Instagram accounts (brands) can run from this one folder. Pick one
with `--account <name>` on any script, or the ACCOUNT environment variable;
the default is fashclick. Each account has accounts/<name>/rules.json, its
own content/<name>/ queue, and these settings (NAME in capitals):
    IG_USER_ID_<NAME>       the account's Instagram id (required)
    IG_ACCESS_TOKEN_<NAME>  only if it needs a different token than IG_ACCESS_TOKEN
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _account_from_args():
    # Read --account here so every script gets the right settings at import time.
    # It's removed from sys.argv so it can go anywhere on the command line,
    # e.g. `content.py add x.mp4 --account vrittos`.
    for i, arg in enumerate(sys.argv):
        if arg == "--account" and i + 1 < len(sys.argv):
            value = sys.argv[i + 1]
            del sys.argv[i:i + 2]
            return value
        if arg.startswith("--account="):
            del sys.argv[i]
            return arg.split("=", 1)[1]
    return None


ACCOUNTS_DIR = BASE_DIR / "accounts"
ACCOUNTS = sorted(p.name for p in ACCOUNTS_DIR.iterdir() if (p / "rules.json").exists()) \
    if ACCOUNTS_DIR.exists() else []
ACCOUNT = (_account_from_args() or os.getenv("ACCOUNT") or "fashclick").strip().lower()
if ACCOUNTS and ACCOUNT not in ACCOUNTS:
    sys.exit("Unknown account {!r}. Choose one of: {}".format(ACCOUNT, ", ".join(ACCOUNTS)))
_SUFFIX = "_" + ACCOUNT.upper()


def _per_account(name, fallback=True):
    """IG_USER_ID_VAANICRAFT, else plain IG_USER_ID (kept for fashclick's original setup)."""
    value = os.getenv(name + _SUFFIX, "")
    if not value and (fallback or ACCOUNT == "fashclick"):
        value = os.getenv(name, "")
    return value


IG_ACCESS_TOKEN = _per_account("IG_ACCESS_TOKEN")
IG_USER_ID = _per_account("IG_USER_ID", fallback=False)
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
IG_MESSAGING_ID = _per_account("IG_MESSAGING_ID", fallback=False) or IG_USER_ID
# The brand's Facebook Page (FB_PAGE_ID_VAANICRAFT ...; fashclick may use plain FB_PAGE_ID).
FB_PAGE_ID = _per_account("FB_PAGE_ID", fallback=False)

# DRY_RUN logs what would be sent to Instagram instead of sending it.
DRY_RUN = _bool("DRY_RUN")
# QUIET_LOGS hides usernames and message text from logs (for public CI logs).
QUIET_LOGS = _bool("QUIET_LOGS")

ACCOUNT_DIR = ACCOUNTS_DIR / ACCOUNT
RULES_FILE = BASE_DIR / os.getenv("RULES_FILE", "accounts/{}/rules.json".format(ACCOUNT))
STATE_FILE = BASE_DIR / os.getenv("STATE_FILE", "state-{}.json".format(ACCOUNT))
CONTENT_DIR = BASE_DIR / "content" / ACCOUNT
PUBLISHED_DIR = BASE_DIR / "published" / ACCOUNT
ENV_FILE = BASE_DIR / ".env"
