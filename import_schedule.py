"""Queue a week's Instagram content straight from the shared schedule file.

    python import_schedule.py "/Users/Sameer/soical media/Schedule/2026-11-04_to_2026-11-10_schedule.json"
    python import_schedule.py <schedule.json> --apply     # actually queue + push

Without --apply it only shows what it would queue. It picks the rows for one
product (the --account, e.g. --account vaanicraft) that go to Instagram, uses the Instagram caption
file, splits off the '---- FIRST COMMENT ----' part, adds reel covers, and
skips anything already queued or already in the past. Safe to run again.
"""
import argparse
import fcntl
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import content
from autoreply import CAPTION_KEYWORD  # same rule the auto-reply bot uses


def rows_for(schedule, product, platforms=("instagram",)):
    """-> (row, when, platform) for each platform the row is meant for (Instagram, Facebook)."""
    # e.g. "Asia/Kolkata (IST, UTC+05:30)" -> Asia/Kolkata
    tz = ZoneInfo(schedule.get("timezone", "Asia/Kolkata").split()[0])
    for row in schedule["items"]:
        if row.get("product", "").lower() != product.lower():
            continue
        when = datetime.strptime(row["date"] + " " + row["time_ist"], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        for platform in platforms:
            if platform in row.get("platforms", "").lower():
                yield row, when, platform


def to_post(row, platform="instagram"):
    """-> (kind, files, caption, first_comment, cover), after checking every file exists."""
    kind, files, caption, first, cover = _to_post(row, platform)
    for f in list(files) + ([Path(cover)] if cover else []):
        if not Path(f).is_file():
            raise FileNotFoundError("missing file {}".format(f))
    return kind, files, caption, first, cover


def _to_post(row, platform="instagram"):
    media = Path(row["media"])
    if not media.exists():
        raise FileNotFoundError("missing {}".format(media))
    if row["type"] == "story":
        return "story", [media], "", "", None
    cap_file = row.get("caption_" + platform)
    caption, first = content.split_first_comment(Path(cap_file).read_text(encoding="utf-8") if cap_file else "")
    if platform == "facebook":
        first = ""   # Facebook captions already end with their question; no separate first comment
    if row["type"] == "reel":
        return "reel", [media], caption, first, (row.get("cover") or None) if platform == "instagram" else None
    # "post" or "carousel (N slides)": a folder of 01.png, 02.png, ...
    slides = sorted(p for p in media.iterdir()
                    if re.fullmatch(r"\d+\.(png|jpe?g|webp|mp4|mov)", p.name, re.I))
    expected = re.search(r"\((\d+) slides?\)", row["type"])
    if expected and int(expected.group(1)) != len(slides):
        sys.exit("{}: schedule says {} slides but the folder has {}".format(media, expected.group(1), len(slides)))
    return ("photo" if len(slides) == 1 else "carousel"), slides, caption, first, None


def main():
    parser = argparse.ArgumentParser(description="Queue Instagram posts from a schedule JSON")
    parser.add_argument("schedule")
    parser.add_argument("--product", help="Product name in the schedule (default: the --account, e.g. VaaniCraft)")
    parser.add_argument("--apply", action="store_true", help="Queue and push (otherwise just preview)")
    parser.add_argument("--facebook", action="store_true", help="Include Facebook rows even without FB_PAGE_ID (preview/testing)")
    args = parser.parse_args()

    schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    if args.apply:
        # Several things can import (auto_import.py, the weekly routine's autopilot_sync.py, a person).
        # Hold a per-brand lock and read the queue only after getting it, so two imports at the same
        # time wait for each other instead of both queuing the same post.
        content.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        lock = open(content.CONTENT_DIR / ".import.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
    existing = set()
    if content.QUEUE_FILE.exists():
        existing = {i.get("origin") for i in content.load_queue(content._key())}
    now = datetime.now().astimezone()

    queued = skipped = errors = 0
    product = args.product or config.ACCOUNT
    print("Account: {}  (schedule product: {})".format(config.ACCOUNT, product))
    platforms = ["instagram"] + (["facebook"] if (config.FB_PAGE_ID or args.facebook) else [])
    print("Platforms: " + ", ".join(platforms) + ("" if "facebook" in platforms else
          "  (Facebook skipped: no FB_PAGE_ID_{} yet)".format(config.ACCOUNT.upper())))
    for row, when, platform in sorted(rows_for(schedule, product, platforms), key=lambda r: (r[1], r[2])):
        origin = "{} {} {} {}".format(row["date"], row["time_ist"], row["type"], row["id"])
        if platform != "instagram":
            origin = platform + "|" + origin   # Instagram keeps the original key, so old queues still match
        slot = "{:<9} {:<20} {}".format(platform, row["type"], when.astimezone().strftime("%a %d %b %H:%M"))
        if origin in existing:
            print("already queued  " + slot)
            skipped += 1
            continue
        if when < now:
            print("in the past     " + slot)
            skipped += 1
            continue
        # One bad item (missing file, wrong photo size...) is reported and skipped;
        # the rest of the week still gets queued. Fix it and run again.
        try:
            kind, files, caption, first, cover = to_post(row, platform)
            label = "{:<9} {:<8} {}  {:>2} file(s){}{}".format(
                platform, kind, when.astimezone().strftime("%a %d %b %H:%M"), len(files),
                "  +cover" if cover else "", "  +1st comment" if first else "")
            keyword = CAPTION_KEYWORD.search(caption) if caption else None
            print("{}  {}  {}".format("QUEUE " if args.apply else "would queue", label,
                                      "keyword " + keyword.group(1) if keyword else ""))
            if args.apply:
                content.queue_item(kind, files, caption, when, first_comment=first, cover=cover,
                                   origin=origin, platform=platform)
            queued += 1
        except (SystemExit, Exception) as exc:
            print("ERROR           {}: {}".format(slot, exc))
            errors += 1

    print("\n{} to queue, {} skipped, {} error(s).".format(queued, skipped, errors))
    if args.apply and queued:
        content.commit_and_push([content.CONTENT_DIR], "Update content queue")
        print("Pushed. GitHub will post each one within ~5-15 minutes of its time.")
    elif queued:
        print("Run again with --apply to queue them.")
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
