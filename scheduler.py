"""Post reels from queue.json when their time comes.

queue.json is a list like:
    [{"video": "reels/day1.mp4", "caption": "...", "post_at": "2026-11-04T09:00:00+05:30"}]

    python scheduler.py          # post anything due, then exit (use with cron)
    python scheduler.py --loop   # keep running, check every 5 minutes
"""
import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from ig_api import InstagramClient, InstagramError

log = logging.getLogger("scheduler")


def load_queue():
    if not config.QUEUE_FILE.exists():
        return []
    return json.loads(config.QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(queue):
    config.QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_time(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # treat naive times as this computer's local time
    return dt


def run_once(client):
    queue = load_queue()
    now = datetime.now(timezone.utc)
    posted_any = False
    for item in queue:
        if item.get("status") in ("posted", "failed"):
            continue
        if parse_time(item["post_at"]) > now:
            continue
        video = item.get("video")
        if video and not Path(video).is_absolute():
            video = str(config.BASE_DIR / video)
        log.info("Posting %s", video or item.get("video_url"))
        try:
            item["media_id"] = client.publish_reel(
                video_path=video, video_url=item.get("video_url"),
                caption=item.get("caption", ""), share_to_feed=item.get("share_to_feed", True),
            )
            item["status"] = "posted"
            item["posted_at"] = datetime.now(timezone.utc).isoformat()
        except InstagramError as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            log.error("Failed: %s", exc)
        save_queue(queue)  # save after each item so a crash never double-posts
        posted_any = True
    if not posted_any:
        log.info("Nothing due.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--every", type=int, default=300, help="Seconds between checks in --loop mode")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = InstagramClient()
    while True:
        run_once(client)
        if not args.loop:
            break
        time.sleep(args.every)


if __name__ == "__main__":
    main()
