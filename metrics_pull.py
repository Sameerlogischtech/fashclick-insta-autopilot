"""Read-only Facebook Page and YouTube channel stats for the content dashboard.

    .venv/bin/python metrics_pull.py --account vaanicraft --days 30 --out "<Insights dir>"

Writes <out>/<YYYY-MM-DD>_<name>_facebook.json and _youtube.json in the same shape as
ig_metrics.py's Instagram files (account, followers, posts with views/reach/likes/comments/shares).
A platform the brand hasn't connected is skipped. Never prints tokens.
"""
import argparse
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

import config
from ig_api import InstagramError

log = logging.getLogger("metrics")


def first_line(text):
    return (text or "").strip().split("\n")[0][:120]


def facebook(days):
    from fb_api import FacebookClient
    fb = FacebookClient(dry_run=False)
    token, base = fb.page_token(), "https://graph.facebook.com/{}/".format(config.GRAPH_API_VERSION)
    get = lambda path, **p: requests.get(base + path, params=dict(p, access_token=token), timeout=60).json()
    page = get(fb.page_id, fields="name,followers_count,fan_count")
    if "error" in page:
        raise InstagramError("Facebook page: {}".format(page["error"].get("message")))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    data = get("{}/published_posts".format(fb.page_id), limit=50,
               fields="id,created_time,message,permalink_url,shares,reactions.summary(total_count).limit(0),"
                      "comments.summary(total_count).limit(0)")
    posts = []
    for p in data.get("data", []):
        ts = datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z")
        if ts < since:
            continue
        row = dict(id=p["id"], timestamp=p["created_time"], media_type="POST", media_product_type="feed",
                   permalink=p.get("permalink_url"), first_line=first_line(p.get("message")),
                   like_count=p.get("reactions", {}).get("summary", {}).get("total_count"),
                   comments_count=p.get("comments", {}).get("summary", {}).get("total_count"),
                   shares=(p.get("shares") or {}).get("count", 0), saved=None)
        ins = get("{}/insights".format(p["id"]), metric="post_media_view,post_total_media_view_unique")
        vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in ins.get("data", [])}
        row["views"], row["reach"] = vals.get("post_media_view"), vals.get("post_total_media_view_unique")
        posts.append(row)
    return dict(account=page.get("name"), followers=page.get("followers_count") or page.get("fan_count"),
                media_count=None, posts=posts)


def youtube(days):
    from yt_api import YouTubeClient
    yt = YouTubeClient(dry_run=False).yt
    ch = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = yt.playlistItems().list(part="contentDetails", maxResults=50,
                                    playlistId=ch["contentDetails"]["relatedPlaylists"]["uploads"]).execute().get("items", [])
    ids = [i["contentDetails"]["videoId"] for i in items]
    posts = []
    for v in (yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids)).execute().get("items", [])
              if ids else []):
        ts = datetime.strptime(v["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if ts < since:
            continue
        st = v.get("statistics", {})
        dur = v.get("contentDetails", {}).get("duration", "")
        short = not re.search(r"\d+H", dur) and int((re.search(r"(\d+)M", dur) or [0, 0])[1]) < 3
        num = lambda k: int(st[k]) if k in st else None
        posts.append(dict(id=v["id"], timestamp=v["snippet"]["publishedAt"], media_type="VIDEO",
                          media_product_type="short" if short else "video",
                          permalink=("https://www.youtube.com/shorts/" if short else "https://www.youtube.com/watch?v=") + v["id"],
                          first_line=v["snippet"]["title"][:120], views=num("viewCount"), reach=None,
                          like_count=num("likeCount"), comments_count=num("commentCount"), saved=None, shares=None))
    s = ch.get("statistics", {})
    return dict(account=ch["snippet"]["title"], followers=int(s.get("subscriberCount", 0)),
                media_count=int(s.get("videoCount", 0)), posts=posts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    os.makedirs(a.out, exist_ok=True)
    for platform, ready, pull in (("facebook", config.FB_PAGE_ID, facebook),
                                  ("youtube", config.YT_REFRESH_TOKEN, youtube)):
        if not ready:
            print("{} {}: not connected, skipped".format(config.ACCOUNT, platform))
            continue
        try:
            d = pull(a.days)
        except Exception as exc:   # one platform failing shouldn't stop the other
            print("{} {}: failed ({})".format(config.ACCOUNT, platform, str(exc)[:160]))
            continue
        d.update(pulled_at=datetime.now().isoformat(timespec="seconds"), platform=platform, brand=config.ACCOUNT,
                 window_days=a.days, insights_available=True)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", d["account"] or config.ACCOUNT)
        path = os.path.join(a.out, "{:%Y-%m-%d}_{}_{}.json".format(datetime.now(), name, platform))
        json.dump(d, open(path, "w"), indent=1, ensure_ascii=False)
        print("{} {}: {} followers, {} posts in last {} days -> {}".format(
            config.ACCOUNT, platform, d["followers"], len(d["posts"]), a.days, path))


if __name__ == "__main__":
    main()
