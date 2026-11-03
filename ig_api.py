"""Thin client for the official Instagram API.

Works with both Meta setups: "Unified login" (system-user token on
graph.facebook.com, the default for new apps) and the older "Instagram login"
(graph.instagram.com). Nothing here needs your Instagram password.
"""
import logging
import os
import time

import requests

import config

log = logging.getLogger("ig_api")

GRAPH = "https://" + config.GRAPH_HOST
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"


class InstagramError(Exception):
    pass


class InstagramClient:
    def __init__(self, token=None, user_id=None, version=None, dry_run=None):
        self.token = token or config.IG_ACCESS_TOKEN
        self.user_id = user_id or config.IG_USER_ID
        self.version = version or config.GRAPH_API_VERSION
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        if not self.dry_run and not (self.token and self.user_id):
            raise InstagramError("IG_ACCESS_TOKEN and IG_USER_ID must be set in .env")

    def _url(self, path):
        return "{}/{}/{}".format(GRAPH, self.version, path.lstrip("/"))

    def _request(self, method, path, params=None, json=None):
        # Dry run fakes only writes; reads still hit Instagram so the poller can see real comments.
        if self.dry_run and method != "GET":
            log.info("[DRY_RUN] %s %s params=%s json=%s", method, path, params, json)
            return {"id": "dry-run-id", "status_code": "FINISHED"}
        params = dict(params or {})
        params["access_token"] = self.token
        resp = requests.request(method, self._url(path), params=params, json=json, timeout=60)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in data:
            raise InstagramError("{} {} failed: {}".format(method, path, data.get("error", data)))
        return data

    # ---------- account ----------

    def token_owner(self):
        """Who the token belongs to (a system user on Unified login)."""
        return self._request("GET", "me", params={"fields": "id,name"})

    def account(self):
        """The Instagram account IG_USER_ID points at."""
        return self._request("GET", self.user_id, params={"fields": "id,username"})

    def find_instagram_accounts(self):
        """Instagram accounts assigned to the system user, or linked through its Pages."""
        found = []
        assigned = self._request("GET", "me/assigned_instagram_accounts",
                                 params={"fields": "id,username"})
        found += [("assigned to system user", a) for a in assigned.get("data", [])]
        pages = self._request("GET", "me/accounts",
                              params={"fields": "name,instagram_business_account{id,username}"})
        found += [("Page " + p["name"], p["instagram_business_account"])
                  for p in pages.get("data", []) if p.get("instagram_business_account")]
        return found

    def subscribe_webhooks(self, fields="comments,messages"):
        """Ask Meta to send this account's events to the app's webhook."""
        return self._request("POST", "{}/subscribed_apps".format(self.user_id),
                             params={"subscribed_fields": fields})

    # ---------- publishing reels ----------

    def publish_reel(self, video_path=None, video_url=None, caption="", share_to_feed=True,
                     cover_url=None, poll_seconds=10, timeout_seconds=900):
        """Upload a reel (local file or public URL), wait for processing, publish it."""
        if not (video_path or video_url):
            raise InstagramError("Give either a local video_path or a public video_url")

        params = {
            "media_type": "REELS",
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
        }
        if cover_url:
            params["cover_url"] = cover_url
        if video_url:
            params["video_url"] = video_url
        else:
            params["upload_type"] = "resumable"

        container = self._request("POST", "{}/media".format(self.user_id), params=params)
        container_id = container["id"]
        log.info("Created media container %s", container_id)

        if video_path:
            self._upload_file(container_id, video_path)

        self._wait_until_ready(container_id, poll_seconds, timeout_seconds)
        published = self._request("POST", "{}/media_publish".format(self.user_id),
                                  params={"creation_id": container_id})
        log.info("Published reel, media id %s", published["id"])
        return published["id"]

    def _upload_file(self, container_id, video_path):
        size = os.path.getsize(video_path)
        if self.dry_run:
            log.info("[DRY_RUN] upload %s (%d bytes) to container %s", video_path, size, container_id)
            return
        url = "{}/{}/{}".format(RUPLOAD, self.version, container_id)
        headers = {
            "Authorization": "OAuth {}".format(self.token),
            "offset": "0",
            "file_size": str(size),
        }
        with open(video_path, "rb") as fh:
            resp = requests.post(url, headers=headers, data=fh, timeout=600)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("success", False):
            raise InstagramError("Video upload failed: {}".format(data))
        log.info("Uploaded %s (%d bytes)", video_path, size)

    def _wait_until_ready(self, container_id, poll_seconds, timeout_seconds):
        if self.dry_run:
            log.info("[DRY_RUN] wait for container %s to finish processing", container_id)
            return
        deadline = time.time() + timeout_seconds
        while True:
            status = self._request("GET", container_id, params={"fields": "status_code,status"})
            code = status.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError("Instagram could not process the video: {}".format(status))
            if time.time() > deadline:
                raise InstagramError("Timed out waiting for Instagram to process the video")
            log.info("Video still processing (%s)...", code)
            time.sleep(poll_seconds)

    # ---------- comments & DMs ----------

    def recent_media(self, limit=10):
        data = self._request("GET", "{}/media".format(self.user_id),
                             params={"fields": "id,timestamp,comments_count,caption", "limit": limit})
        return data.get("data", [])

    def media_caption(self, media_id):
        return self._request("GET", media_id, params={"fields": "caption"}).get("caption", "")

    def media_comments(self, media_id, limit=50):
        data = self._request("GET", "{}/comments".format(media_id),
                             params={"fields": "id,text,timestamp,from{id,username},username",
                                     "limit": limit})
        return data.get("data", [])

    def recent_conversations(self, limit=10, messages_per_thread=5):
        fields = "id,updated_time,messages.limit({}){{id,message,from,created_time}}".format(
            messages_per_thread)
        data = self._request("GET", "{}/conversations".format(config.IG_MESSAGING_ID),
                             params={"platform": "instagram", "fields": fields, "limit": limit})
        return data.get("data", [])

    def reply_to_comment(self, comment_id, text):
        """Public reply under a comment."""
        return self._request("POST", "{}/replies".format(comment_id), params={"message": text})

    def private_reply(self, comment_id, text):
        """One DM to the person who left the comment (allowed within 7 days of it)."""
        return self._request("POST", "{}/messages".format(config.IG_MESSAGING_ID),
                             json={"recipient": {"comment_id": comment_id},
                                   "message": {"text": text}})

    def send_dm(self, recipient_id, text):
        """DM reply to someone who messaged you (allowed within 24h of their message)."""
        return self._request("POST", "{}/messages".format(config.IG_MESSAGING_ID),
                             json={"recipient": {"id": recipient_id},
                                   "message": {"text": text}})

    # ---------- token ----------

    def refresh_token(self):
        """Extend the long-lived token by another 60 days (Instagram login only)."""
        if "graph.instagram.com" not in GRAPH:
            raise InstagramError("Unified login system-user tokens never expire; no refresh needed.")
        if self.dry_run:
            log.info("[DRY_RUN] refresh token")
            return {"access_token": self.token, "expires_in": 0}
        resp = requests.get("{}/refresh_access_token".format(GRAPH),
                            params={"grant_type": "ig_refresh_token", "access_token": self.token},
                            timeout=30)
        data = resp.json()
        if "access_token" not in data:
            raise InstagramError("Token refresh failed: {}".format(data))
        return data
