"""Thin client for posting to a brand's Facebook Page (Graph API).

The brand's system-user token (the same one used for Instagram, once it has the
pages_* permissions) is exchanged for the Page's own token, which does the posting.
Photos must be at a public image_url; videos upload straight from disk.
"""
import logging
import os
import time

import requests

import config
from ig_api import InstagramError

log = logging.getLogger("fb_api")

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/video-upload"


class FacebookClient:
    def __init__(self, page_id=None, token=None, version=None, dry_run=None):
        self.page_id = page_id or config.FB_PAGE_ID
        self.user_token = token or config.IG_ACCESS_TOKEN
        self.version = version or config.GRAPH_API_VERSION
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self._page_token = None
        if not self.dry_run and not (self.page_id and self.user_token):
            raise InstagramError("FB_PAGE_ID_{} isn't set".format(config.ACCOUNT.upper()))

    def _url(self, path):
        return "{}/{}/{}".format(GRAPH, self.version, path.lstrip("/"))

    def page_token(self):
        if not self._page_token:
            data = requests.get(self._url(self.page_id), params={"fields": "access_token",
                                                                 "access_token": self.user_token}, timeout=30).json()
            if "access_token" not in data:
                raise InstagramError("Can't get the Page token: {}".format(data.get("error", data)))
            self._page_token = data["access_token"]
        return self._page_token

    def _request(self, method, path, params=None, data=None):
        # Dry run fakes only writes, like the Instagram client.
        if self.dry_run and method != "GET":
            log.info("[DRY_RUN] FB %s %s %s", method, path, {k: v for k, v in (params or data or {}).items()})
            return {"id": "fb-dry-run-id", "video_id": "fb-dry-run-video", "post_id": "fb-dry-run-post",
                    "upload_url": "dry", "success": True}
        params = dict(params or {})
        params["access_token"] = self.page_token()
        resp = requests.request(method, self._url(path), params=params, data=data, timeout=120)
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in body:
            raise InstagramError("FB {} {} failed: {}".format(method, path, body.get("error", body)))
        return body

    # ---------- uploads ----------

    def _upload_video(self, start_path, video_path):
        """start -> rupload -> returns video_id (shared by reels and video stories)."""
        start = self._request("POST", start_path, params={"upload_phase": "start"})
        video_id = start["video_id"]
        size = os.path.getsize(video_path)
        if self.dry_run:
            log.info("[DRY_RUN] FB upload %s (%d bytes) as video %s", video_path, size, video_id)
            return video_id
        with open(video_path, "rb") as fh:
            resp = requests.post(start.get("upload_url") or "{}/{}/{}".format(RUPLOAD, self.version, video_id),
                                 headers={"Authorization": "OAuth " + self.page_token(),
                                          "offset": "0", "file_size": str(size)}, data=fh, timeout=600)
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not body.get("success", False):
            raise InstagramError("FB video upload failed: {}".format(body))
        return video_id

    def _wait_processed(self, video_id, timeout_seconds=600):
        if self.dry_run:
            return
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            st = self._request("GET", video_id, params={"fields": "status"}).get("status", {})
            if st.get("video_status") in ("ready", "upload_complete", "published") or \
                    st.get("processing_phase", {}).get("status") == "complete":
                return
            if st.get("video_status") == "error":
                raise InstagramError("Facebook couldn't process the video: {}".format(st))
            time.sleep(10)

    # ---------- publishing ----------

    def publish_reel(self, video_path, description=""):
        path = "{}/video_reels".format(self.page_id)
        video_id = self._upload_video(path, video_path)
        self._request("POST", path, params={"upload_phase": "finish", "video_id": video_id,
                                            "video_state": "PUBLISHED", "description": description})
        log.info("Published Facebook reel, video id %s", video_id)
        return video_id

    def publish_video(self, video_path, description=""):
        """A normal (long) Page video."""
        if self.dry_run:
            log.info("[DRY_RUN] FB video upload %s", video_path)
            return "fb-dry-run-video"
        with open(video_path, "rb") as fh:
            resp = requests.post(self._url("{}/videos".format(self.page_id)), timeout=1800,
                                 data={"description": description, "access_token": self.page_token()},
                                 files={"source": (os.path.basename(video_path), fh, "video/mp4")})
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in body:
            raise InstagramError("FB video upload failed: {}".format(body.get("error", body)))
        log.info("Published Facebook video %s", body["id"])
        return body["id"]

    def publish_photo(self, image_url, message=""):
        r = self._request("POST", "{}/photos".format(self.page_id), data={"url": image_url, "message": message})
        log.info("Published Facebook photo, post id %s", r.get("post_id") or r["id"])
        return r.get("post_id") or r["id"]

    def publish_album(self, image_urls, message=""):
        """Several photos in one feed post (Facebook's version of a carousel)."""
        ids = [self._request("POST", "{}/photos".format(self.page_id),
                             data={"url": u, "published": "false"})["id"] for u in image_urls]
        data = {"message": message}
        for n, i in enumerate(ids):
            data["attached_media[{}]".format(n)] = '{"media_fbid":"%s"}' % i
        r = self._request("POST", "{}/feed".format(self.page_id), data=data)
        log.info("Published Facebook album post %s (%d photos)", r["id"], len(ids))
        return r["id"]

    def publish_story(self, image_url=None, video_path=None):
        if image_url:
            photo = self._request("POST", "{}/photos".format(self.page_id),
                                  data={"url": image_url, "published": "false"})["id"]
            r = self._request("POST", "{}/photo_stories".format(self.page_id), data={"photo_id": photo})
        else:
            path = "{}/video_stories".format(self.page_id)
            video_id = self._upload_video(path, video_path)
            r = self._request("POST", path, params={"upload_phase": "finish", "video_id": video_id})
        log.info("Published Facebook story %s", r.get("post_id") or r.get("id"))
        return r.get("post_id") or r.get("id") or "story"

    def permalink(self, object_id):
        if self.dry_run:
            return ""
        try:
            d = self._request("GET", object_id, params={"fields": "permalink_url"})
        except InstagramError:
            return ""
        link = d.get("permalink_url", "")
        return ("https://www.facebook.com" + link) if link.startswith("/") else link

    # ---------- setup check ----------

    def page_info(self):
        return self._request("GET", self.page_id, params={"fields": "id,name,link,followers_count,fan_count"})
