"""Checks your latest posts and DMs every minute and answers them with rules.json.

Works while the Meta app is unpublished, and needs no webhook, ngrok or server:
only this script running.

    python poller.py                 # keep running, check every 60 seconds
    python poller.py --once          # check one time and exit
    python poller.py --since 3h      # also answer comments from the last 3 hours

On its first run it only answers comments made after it started (or after
--since), so older comments never get a surprise reply.
"""
import argparse
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import config
from autoreply import client, handle_comment, handle_message, update_state
from ig_api import InstagramError

log = logging.getLogger("poller")


def parse_ig_time(value):
    # Instagram sends times like 2026-11-03T07:22:41+0000
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


def parse_since(text):
    m = re.fullmatch(r"(\d+)([mhd])", text)
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 30m, 3h or 2d")
    unit = {"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
    return timedelta(**{unit: int(m.group(1))})


def start_time(since):
    """Comments older than this are ignored. Saved so restarts don't lose it."""
    def pick(state):
        if since is not None:
            state["poll_since"] = (datetime.now(timezone.utc) - since).isoformat()
        state.setdefault("poll_since", datetime.now(timezone.utc).isoformat())
        return state["poll_since"]
    return datetime.fromisoformat(update_state(pick))


def check_comments(cutoff, media_limit):
    answered = 0
    for media in client.recent_media(limit=media_limit):
        if not media.get("comments_count"):
            continue
        for c in client.media_comments(media["id"]):
            if parse_ig_time(c["timestamp"]) < cutoff:
                continue
            sender = c.get("from") or {"username": c.get("username")}
            answered += bool(handle_comment(
                {"id": c["id"], "text": c.get("text", ""), "from": sender,
                 "media": {"id": media["id"], "caption": media.get("caption", "")}}))
    return answered


def check_messages(cutoff):
    answered = 0
    for convo in client.recent_conversations():
        for msg in convo.get("messages", {}).get("data", []):
            if parse_ig_time(msg["created_time"]) < cutoff:
                continue
            answered += bool(handle_message(
                {"sender": msg.get("from", {}),
                 "message": {"mid": msg["id"], "text": msg.get("message", "")}}))
    return answered


def main():
    parser = argparse.ArgumentParser(description="Answer Instagram comments and DMs by polling")
    parser.add_argument("--once", action="store_true", help="Check one time and exit")
    parser.add_argument("--every", type=int, default=60, help="Seconds between checks")
    parser.add_argument("--since", type=parse_since, help="Answer comments this old too, e.g. 3h")
    parser.add_argument("--posts", type=int, default=10, help="How many recent posts to watch")
    parser.add_argument("--no-dms", action="store_true", help="Only handle comments")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if client is None:
        log.info("[%s] Not set up yet (no IG_USER_ID_%s); skipping.", config.ACCOUNT, config.ACCOUNT.upper())
        return
    cutoff = start_time(args.since)
    log.info("Watching %s's last %d posts%s, answering anything after %s%s",
             "the account" if config.QUIET_LOGS else config.IG_USER_ID, args.posts,
             "" if args.no_dms else " and DMs",
             cutoff.astimezone().strftime("%d %b %H:%M %Z"), " [DRY_RUN]" if config.DRY_RUN else "")

    dms_enabled = not args.no_dms
    while True:
        comments = dms = 0
        try:
            comments = check_comments(cutoff, args.posts)
        except InstagramError as exc:
            log.error("Comment check failed: %s", exc)
        if dms_enabled:
            try:
                dms = check_messages(cutoff)
            except InstagramError as exc:
                # Reading DMs may need a published app; keep comments working regardless.
                log.warning("Can't read DMs, so DM keyword replies are off: %s", exc)
                dms_enabled = False
        log.info("Answered %d comment(s) and %d DM(s) this check.", comments, dms)
        if args.once:
            break
        time.sleep(args.every)


if __name__ == "__main__":
    main()
