"""Queue a week's Instagram content straight from the shared schedule file.

    python import_schedule.py "/Users/Sameer/soical media/Schedule/2026-11-04_to_2026-11-10_schedule.json"
    python import_schedule.py <schedule.json> --apply     # actually queue + push

Without --apply it only shows what it would queue. It picks the rows for one
product (FashClick by default) that go to Instagram, uses the Instagram caption
file, splits off the '---- FIRST COMMENT ----' part, adds reel covers, and
skips anything already queued or already in the past. Safe to run again.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import content
from autoreply import CAPTION_KEYWORD  # same rule the auto-reply bot uses


def rows_for(schedule, product):
    # e.g. "Asia/Kolkata (IST, UTC+05:30)" -> Asia/Kolkata
    tz = ZoneInfo(schedule.get("timezone", "Asia/Kolkata").split()[0])
    for row in schedule["items"]:
        if row.get("product") != product or "instagram" not in row.get("platforms", "").lower():
            continue
        when = datetime.strptime(row["date"] + " " + row["time_ist"], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        yield row, when


def to_post(row):
    """-> (kind, files, caption, first_comment, cover)"""
    media = Path(row["media"])
    if row["type"] == "story":
        return "story", [media], "", "", None
    caption, first = content.split_first_comment(
        Path(row["caption_instagram"]).read_text(encoding="utf-8") if row.get("caption_instagram") else "")
    if row["type"] == "reel":
        return "reel", [media], caption, first, (row.get("cover") or None)
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
    parser.add_argument("--product", default="FashClick")
    parser.add_argument("--apply", action="store_true", help="Queue and push (otherwise just preview)")
    args = parser.parse_args()

    schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    existing = set()
    if content.QUEUE_FILE.exists():
        existing = {i.get("origin") for i in content.load_queue(content._key())}
    now = datetime.now().astimezone()

    queued = skipped = 0
    for row, when in sorted(rows_for(schedule, args.product), key=lambda r: r[1]):
        origin = "{} {} {} {}".format(row["date"], row["time_ist"], row["type"], row["id"])
        kind, files, caption, first, cover = to_post(row)
        label = "{:<8} {}  {:>2} file(s){}{}".format(
            kind, when.astimezone().strftime("%a %d %b %H:%M"), len(files),
            "  +cover" if cover else "", "  +1st comment" if first else "")
        if origin in existing:
            print("already queued  " + label)
            skipped += 1
            continue
        if when < now:
            print("in the past     " + label)
            skipped += 1
            continue
        keyword = CAPTION_KEYWORD.search(caption) if caption else None
        print("{}  {}  {}".format("QUEUE " if args.apply else "would queue", label,
                                  "keyword " + keyword.group(1) if keyword else ""))
        if args.apply:
            content.queue_item(kind, files, caption, when, first_comment=first, cover=cover, origin=origin)
        queued += 1

    print("\n{} to queue, {} skipped.".format(queued, skipped))
    if args.apply and queued:
        content.commit_and_push([content.CONTENT_DIR], "Update content queue")
        print("Pushed. GitHub will post each one within ~5-15 minutes of its time.")
    elif queued:
        print("Run again with --apply to queue them.")


if __name__ == "__main__":
    main()
