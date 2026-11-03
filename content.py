"""Schedule reels, photo posts, carousels and stories, posted by GitHub Actions
even while your Mac is off.

Your upcoming files and captions are stored ENCRYPTED in the repo (content/),
so nobody can see them before they go live. Photos are copied to published/
(public) only at the moment they're posted, because Instagram must download
them from a public link. Videos upload straight to Instagram.

    python content.py add reels/saree.mp4 --at "2026-11-05 18:00"
    python content.py add photo.jpg --caption "New drop ✨" --at "2026-11-06 10:00"
    python content.py add a.jpg b.jpg c.jpg --at "tomorrow 09:30"          # carousel
    python content.py add story.mp4 --type story --at "2026-11-05 20:00"
    python content.py list
    python content.py remove ab12cd
    python content.py retry ab12cd        # try a failed post again
    python content.py post-due            # what the cloud runs every 5 minutes
"""
import argparse
import base64
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import config

log = logging.getLogger("content")

CONTENT_DIR = config.BASE_DIR / "content"
FILES_DIR = CONTENT_DIR / "files"
QUEUE_FILE = CONTENT_DIR / "queue.enc"
POSTED_FILE = CONTENT_DIR / "posted.json"   # written by the poster; ids and media ids only
PUBLISHED_DIR = config.BASE_DIR / "published"

VIDEO_EXTS = {".mp4", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_BYTES = 95 * 1024 * 1024   # GitHub refuses files over 100 MB
TYPES = ("reel", "photo", "carousel", "story")


# ---------- encryption (AES-256-GCM; key lives in .env / GitHub secret CONTENT_KEY) ----------

def _key(create=False):
    key = os.getenv("CONTENT_KEY", "").strip()
    if key:
        # Restore '=' padding that copy/paste or `cut -d=` can drop.
        return base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    if not create:
        sys.exit("CONTENT_KEY is missing. Add it to .env (locally) or the GitHub secrets (cloud).")
    raw = secrets.token_bytes(32)
    with open(config.ENV_FILE, "a", encoding="utf-8") as fh:
        fh.write("\n# Encrypts scheduled posts. Also add it as GitHub secret CONTENT_KEY.\n"
                 "CONTENT_KEY={}\n".format(base64.urlsafe_b64encode(raw).decode()))
    os.environ["CONTENT_KEY"] = base64.urlsafe_b64encode(raw).decode()
    print("Created a new CONTENT_KEY in .env. Run this once so the cloud can read your posts:\n"
          "  gh secret set CONTENT_KEY --body \"$(grep ^CONTENT_KEY= .env | cut -d= -f2-)\"")
    return raw


def encrypt(data, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt(blob, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


# ---------- queue storage ----------

def load_queue(key):
    if not QUEUE_FILE.exists():
        return []
    return json.loads(decrypt(QUEUE_FILE.read_bytes(), key))


def save_queue(queue, key):
    CONTENT_DIR.mkdir(exist_ok=True)
    QUEUE_FILE.write_bytes(encrypt(json.dumps(queue, ensure_ascii=False).encode(), key))


def load_posted():
    return json.loads(POSTED_FILE.read_text()) if POSTED_FILE.exists() else {}


def save_posted(posted):
    POSTED_FILE.write_text(json.dumps(posted, indent=1, sort_keys=True) + "\n")


# ---------- git helpers ----------

def git(*args, check=True):
    return subprocess.run(["git"] + list(args), cwd=config.BASE_DIR, check=check,
                          capture_output=True, text=True).stdout.strip()


def commit_and_push(paths, message):
    git("add", "-A", *[str(p) for p in paths])
    if not git("status", "--porcelain", *[str(p) for p in paths]):
        return
    git("-c", "user.name=insta-autopilot", "-c", "user.email=autopilot@users.noreply.github.com",
        "commit", "-q", "-m", message)
    for attempt in range(3):
        if subprocess.run(["git", "push", "-q"], cwd=config.BASE_DIR).returncode == 0:
            return
        git("pull", "-q", "--rebase", check=False)
    raise RuntimeError("git push failed")


def repo_slug():
    if os.getenv("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = git("remote", "get-url", "origin")
    return url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")


# ---------- adding posts ----------

def parse_when(text):
    now = datetime.now().astimezone()
    if not text or text == "now":
        return now
    words = text.split()
    if words[0] in ("today", "tomorrow"):
        day = now.date() + timedelta(days=1 if words[0] == "tomorrow" else 0)
        hm = datetime.strptime(words[1], "%H:%M").time()
        return datetime.combine(day, hm).astimezone()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).astimezone()
        except ValueError:
            pass
    sys.exit("Couldn't read the time {!r}. Use e.g. \"2026-11-05 18:00\" or \"tomorrow 09:30\".".format(text))


def prepare_image(path, kind):
    """Convert to JPEG (Instagram only takes JPEG) and check the shape."""
    from PIL import Image
    img = Image.open(path)
    ratio = img.width / img.height
    if kind in ("photo", "carousel") and not 0.8 <= ratio <= 1.91:
        sys.exit("{}: feed photos must be between 4:5 (portrait) and 1.91:1 (landscape); "
                 "this one is {}x{}. Crop it to 1080x1350 for portrait.".format(path, img.width, img.height))
    img = img.convert("RGB")
    out = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(out.name, "JPEG", quality=92)
    return Path(out.name)


def split_first_comment(text):
    """Captions may end with '---- FIRST COMMENT ... ----'; that part becomes the first comment."""
    marker = "---- FIRST COMMENT"
    if marker not in text:
        return text.strip(), ""
    caption, rest = text.split(marker, 1)
    rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    return caption.strip(), rest.strip()


def cmd_add(args):
    caption = args.caption
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8")
    elif caption is None and Path(args.files[0]).with_suffix(".txt").exists():
        caption = Path(args.files[0]).with_suffix(".txt").read_text(encoding="utf-8")
    caption, first_comment = split_first_comment(caption or "")
    item_id = queue_item(args.type, args.files, caption, parse_when(args.at),
                         first_comment=args.first_comment or first_comment, cover=args.cover)
    if not args.no_push:
        # A neutral message: commit messages are public.
        commit_and_push([CONTENT_DIR], "Update content queue")
        print("Pushed. The cloud will post it within ~5-15 minutes of that time.")
    return item_id


def queue_item(kind, files, caption, when, first_comment="", cover=None, origin=None):
    """Validate, encrypt and add one post to the queue (not pushed). Returns its id."""
    key = _key(create=True)
    files = [Path(f) for f in files]
    for f in files:
        if not f.exists():
            sys.exit("File not found: {}".format(f))
        if f.suffix.lower() not in VIDEO_EXTS | IMAGE_EXTS:
            sys.exit("{}: use .mp4/.mov videos or .jpg/.png images".format(f))

    if not kind:
        if len(files) > 1:
            kind = "carousel"
        else:
            kind = "reel" if files[0].suffix.lower() in VIDEO_EXTS else "photo"
    if kind == "reel" and (len(files) != 1 or files[0].suffix.lower() not in VIDEO_EXTS):
        sys.exit("A reel is exactly one video.")
    if kind == "photo" and (len(files) != 1 or files[0].suffix.lower() not in IMAGE_EXTS):
        sys.exit("A photo post is exactly one image.")
    if kind == "story" and len(files) != 1:
        sys.exit("A story is one photo or one video. Add several stories one at a time.")
    if kind == "carousel" and not 2 <= len(files) <= 10:
        sys.exit("A carousel needs 2 to 10 photos/videos.")

    caption = (caption or "").strip()
    if kind == "story" and (caption or first_comment):
        print("Note: stories have no caption or comments; ignoring them.")
        caption = first_comment = ""
    if len(caption) > 2200:
        sys.exit("Caption is {} characters; Instagram allows 2,200.".format(len(caption)))
    if caption.count("#") > 30:
        sys.exit("Instagram allows at most 30 hashtags.")
    if cover and kind != "reel":
        sys.exit("A cover image is only for reels.")

    item_id = secrets.token_hex(3)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    def store(path, name, as_kind):
        is_video = path.suffix.lower() in VIDEO_EXTS
        data = (path if is_video else prepare_image(path, as_kind)).read_bytes()
        if len(data) > MAX_FILE_BYTES:
            sys.exit("{} is {:.0f} MB; keep each file under 95 MB.".format(path, len(data) / 1e6))
        (FILES_DIR / name).write_bytes(encrypt(data, key))
        return {"name": name, "ext": ".mp4" if is_video else ".jpg"}

    stored = [store(f, "{}-{}.enc".format(item_id, n), kind) for n, f in enumerate(files)]
    item = {"id": item_id, "type": kind, "files": stored, "caption": caption,
            "first_comment": first_comment, "post_at": when.isoformat(),
            "added_at": datetime.now().astimezone().isoformat(), "source": [f.name for f in files]}
    if cover:
        item["cover"] = store(Path(cover), "{}-cover.enc".format(item_id), "cover")
    if origin:
        item["origin"] = origin

    queue = load_queue(key)
    queue.append(item)
    save_queue(queue, key)
    print("Queued {:<8} {:<16} {} (id {}){}".format(
        kind, when.strftime("%a %d %b %H:%M"), ", ".join(f.name for f in files)[:60], item_id,
        " + cover" if cover else ""))
    return item_id


def cmd_list(args):
    key = _key()
    posted = load_posted()
    queue = sorted(load_queue(key), key=lambda i: i["post_at"])
    if not queue:
        print("Nothing scheduled.")
    for item in queue:
        state = posted.get(item["id"], {})
        status = state.get("status", "waiting")
        when = datetime.fromisoformat(item["post_at"]).astimezone().strftime("%a %d %b %H:%M")
        extra = state.get("permalink") or state.get("error", "")
        print("{}  {:<8} {:<8} {:<16} {}  {}".format(item["id"], item["type"], status, when,
                                                    ", ".join(item.get("source", [])), extra)[:200])


def cmd_remove(args):
    key = _key()
    queue = load_queue(key)
    item = next((i for i in queue if i["id"] == args.id), None)
    if not item:
        sys.exit("No item with id {}".format(args.id))
    for f in item["files"]:
        (FILES_DIR / f["name"]).unlink(missing_ok=True)
    save_queue([i for i in queue if i["id"] != args.id], key)
    commit_and_push([CONTENT_DIR], "Update content queue")
    print("Removed {}.".format(args.id))


def cmd_retry(args):
    posted = load_posted()
    if posted.pop(args.id, None) is None:
        sys.exit("{} hasn't been tried yet.".format(args.id))
    save_posted(posted)
    commit_and_push([POSTED_FILE], "Retry a scheduled post")
    print("{} will be tried again on the next run.".format(args.id))


# ---------- posting (runs in the cloud) ----------

def publish_images(item, decrypted):
    """Copy this post's photos to published/ and return their public URLs."""
    PUBLISHED_DIR.mkdir(exist_ok=True)
    names = {}
    for f, path in decrypted:
        if f["ext"] == ".jpg":
            dest = PUBLISHED_DIR / "{}{}".format(f["name"][:-4], ".jpg")
            shutil.copy(path, dest)
            names[f["name"]] = dest.name
    if not names:
        return {}
    if config.DRY_RUN:
        return {k: "https://example.invalid/" + v for k, v in names.items()}
    commit_and_push([PUBLISHED_DIR], "Publish photos for a post")
    sha = git("rev-parse", "HEAD")
    urls = {k: "https://raw.githubusercontent.com/{}/{}/published/{}".format(repo_slug(), sha, v)
            for k, v in names.items()}
    for url in urls.values():   # GitHub can take a few seconds to serve a new file
        for _ in range(12):
            if requests.head(url, timeout=10).status_code == 200:
                break
            time.sleep(5)
    return urls


def post_item(client, item, key, workdir):
    def unpack(f):
        path = Path(workdir) / (f["name"][:-4] + f["ext"])
        path.write_bytes(decrypt((FILES_DIR / f["name"]).read_bytes(), key))
        return f, path

    decrypted = [unpack(f) for f in item["files"]]
    cover = unpack(item["cover"]) if item.get("cover") else None
    urls = publish_images(item, decrypted + ([cover] if cover else []))

    kind, caption = item["type"], item.get("caption", "")
    f, path = decrypted[0]
    if kind == "reel":
        return client.publish_reel(video_path=str(path), caption=caption,
                                   cover_url=urls[cover[0]["name"]] if cover else None)
    if kind == "photo":
        return client.publish_photo(urls[f["name"]], caption)
    if kind == "story":
        if f["ext"] == ".jpg":
            return client.publish_story(image_url=urls[f["name"]])
        return client.publish_story(video_path=str(path))
    if kind == "carousel":
        items = [{"image_url": urls[f["name"]]} if f["ext"] == ".jpg" else {"video_path": str(p)}
                 for f, p in decrypted]
        return client.publish_carousel(items, caption)
    raise ValueError("unknown type " + kind)


def cmd_post_due(args):
    from ig_api import InstagramClient, InstagramError
    if not QUEUE_FILE.exists():
        log.info("Nothing scheduled yet.")
        return
    key = _key()
    queue = load_queue(key)
    posted = load_posted()
    now = datetime.now(timezone.utc)
    due = [i for i in sorted(queue, key=lambda i: i["post_at"])
           if i["id"] not in posted and datetime.fromisoformat(i["post_at"]) <= now]
    log.info("%d scheduled item(s), %d due now%s", len(queue), len(due), " [DRY_RUN]" if config.DRY_RUN else "")
    if not due:
        return
    client = InstagramClient()
    for item in due:
        log.info("Posting %s %s", item["type"], item["id"])
        with tempfile.TemporaryDirectory() as workdir:
            try:
                media_id = post_item(client, item, key, workdir)
                record = {"status": "posted", "media_id": media_id,
                          "permalink": client.permalink(media_id)}
                if item.get("first_comment"):
                    # A failed comment shouldn't mark the post itself as failed.
                    try:
                        client.comment(media_id, item["first_comment"])
                        record["first_comment"] = "posted (pin it in the app)"
                    except InstagramError as exc:
                        record["first_comment"] = "failed: {}".format(str(exc)[:200])
            except (InstagramError, RuntimeError, KeyError) as exc:
                log.error("Failed to post %s: %s", item["id"], exc)
                record = {"status": "failed", "error": str(exc)[:300]}
        record["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log.info("%s -> %s %s", item["id"], record["status"], record.get("permalink", ""))
        if config.DRY_RUN:
            continue
        posted[item["id"]] = record
        save_posted(posted)
        commit_and_push([POSTED_FILE], "Record posted content")


def main():
    parser = argparse.ArgumentParser(description="Schedule Instagram reels, posts, carousels and stories")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="Schedule a post")
    add.add_argument("files", nargs="+")
    add.add_argument("--type", choices=TYPES, help="Default: reel for one video, photo for one image, carousel for several")
    add.add_argument("--caption")
    add.add_argument("--caption-file", help="A '---- FIRST COMMENT ----' section in it becomes the first comment")
    add.add_argument("--first-comment", help="Comment to add right after posting")
    add.add_argument("--cover", help="Cover image for a reel")
    add.add_argument("--at", help='When to post, e.g. "2026-11-05 18:00", "tomorrow 09:30" or "now"')
    add.add_argument("--no-push", action="store_true", help="Don't push to GitHub yet")
    sub.add_parser("list", help="Show scheduled posts and their status")
    rm = sub.add_parser("remove", help="Unschedule a post")
    rm.add_argument("id")
    rt = sub.add_parser("retry", help="Try a failed post again")
    rt.add_argument("id")
    sub.add_parser("post-due", help="Post everything that's due (the cloud runs this)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    {"add": cmd_add, "list": cmd_list, "remove": cmd_remove, "retry": cmd_retry,
     "post-due": cmd_post_due}[args.cmd](args)


if __name__ == "__main__":
    main()
