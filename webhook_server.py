"""Receives Instagram webhooks and answers comments and DMs using rules.json.

    python webhook_server.py                  # local, port 8000
    gunicorn webhook_server:app               # on a host like Render/Railway

Instagram must be able to reach this server over HTTPS, and Meta only sends
events to published (Live) apps; see README. Use poller.py otherwise.
"""
import hashlib
import hmac
import json
import logging
import os
import threading

from flask import Flask, abort, request

import config
from autoreply import process

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("webhook")

app = Flask(__name__)


def signature_ok(raw_body, header):
    if not config.IG_APP_SECRET:
        log.warning("IG_APP_SECRET not set; skipping signature check (only OK for local testing)")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(config.IG_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@app.get("/webhook")
def verify():
    """Meta calls this once when you add the webhook URL."""
    if (request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == config.WEBHOOK_VERIFY_TOKEN):
        return request.args.get("hub.challenge", ""), 200
    abort(403)


@app.post("/webhook")
def receive():
    raw = request.get_data()
    if not signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected webhook with bad signature")
        abort(403)
    payload = json.loads(raw or b"{}")
    # Answer Meta fast; do the API calls in the background.
    threading.Thread(target=process, args=(payload,), daemon=True).start()
    return "ok", 200


@app.get("/")
def health():
    return {"status": "running", "dry_run": config.DRY_RUN}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
