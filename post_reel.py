"""Post one reel right now.

    python post_reel.py reels/my_reel.mp4 --caption "Hook line... #tag"
    python post_reel.py reels/my_reel.mp4 --caption-file reels/my_reel.txt
    python post_reel.py --video-url https://example.com/reel.mp4 --caption "..."
"""
import argparse
import logging
import sys
from pathlib import Path

from ig_api import InstagramClient, InstagramError


def main():
    parser = argparse.ArgumentParser(description="Publish a reel to Instagram")
    parser.add_argument("video", nargs="?", help="Path to a local .mp4")
    parser.add_argument("--video-url", help="Public URL of the video instead of a local file")
    parser.add_argument("--caption", default=None)
    parser.add_argument("--caption-file", help="Text file holding the caption")
    parser.add_argument("--cover-url", help="Optional public URL of a cover image")
    parser.add_argument("--no-feed", action="store_true", help="Show only in the Reels tab, not the grid")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    caption = args.caption or ""
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8").strip()
    elif args.caption is None and args.video:
        sidecar = Path(args.video).with_suffix(".txt")
        if sidecar.exists():
            caption = sidecar.read_text(encoding="utf-8").strip()

    try:
        media_id = InstagramClient().publish_reel(
            video_path=args.video, video_url=args.video_url, caption=caption,
            share_to_feed=not args.no_feed, cover_url=args.cover_url,
        )
    except InstagramError as exc:
        logging.error(str(exc))
        sys.exit(1)
    print("Posted! media id: {}".format(media_id))


if __name__ == "__main__":
    main()
