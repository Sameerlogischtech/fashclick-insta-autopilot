"""Thin client for uploading to a brand's YouTube channel (YouTube Data API v3).

Uses a refresh token from a one-time Google sign-in per channel (yt_auth.py), so
no password is stored. Shorts are vertical videos under 3 minutes with #Shorts in
the title; long videos are uploaded the same way, with their thumbnail.
"""
import logging

import config
from ig_api import InstagramError

log = logging.getLogger("yt_api")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/youtube.readonly"]


class YouTubeClient:
    def __init__(self, refresh_token=None, dry_run=None):
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self.refresh_token = refresh_token or config.YT_REFRESH_TOKEN
        self._yt = None
        if not self.dry_run and not (self.refresh_token and config.YT_CLIENT_ID and config.YT_CLIENT_SECRET):
            raise InstagramError("YouTube isn't connected for {} (run yt_auth.py)".format(config.ACCOUNT))

    @property
    def yt(self):
        if self._yt is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds = Credentials(None, refresh_token=self.refresh_token, client_id=config.YT_CLIENT_ID,
                                client_secret=config.YT_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token",
                                scopes=SCOPES)
            self._yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._yt

    def _call(self, what, request):
        from googleapiclient.errors import HttpError
        try:
            return request.execute()
        except HttpError as exc:
            raise InstagramError("YouTube {} failed: {}".format(what, exc)) from exc

    def channel(self):
        data = self._call("channel lookup", self.yt.channels().list(part="snippet,statistics", mine=True))
        items = data.get("items") or [{}]
        return dict(id=items[0].get("id"), title=items[0].get("snippet", {}).get("title"),
                    subscribers=items[0].get("statistics", {}).get("subscriberCount"))

    def upload(self, video_path, title, description="", thumbnail_path=None, privacy="public"):
        """Upload a Short or long video. Returns the video id."""
        body = {
            "snippet": {"title": (title or "Untitled")[:100], "description": (description or "")[:5000],
                        "categoryId": "22"},
            # Every person in this content is AI-generated: YouTube's "altered or synthetic content" label.
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        }
        if self.dry_run:
            log.info("[DRY_RUN] YouTube upload %s as %r (%s)", video_path, body["snippet"]["title"], privacy)
            return "yt-dry-run-id"
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        request = self.yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        try:
            while response is None:
                _, response = request.next_chunk()
        except HttpError as exc:
            raise InstagramError("YouTube upload failed: {}".format(exc)) from exc
        video_id = response["id"]
        log.info("Uploaded to YouTube, video id %s", video_id)
        if thumbnail_path:
            try:
                self._call("thumbnail", self.yt.thumbnails().set(
                    videoId=video_id, media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")))
            except InstagramError as exc:   # needs a verified channel; the video itself is fine
                log.warning("Thumbnail not set: %s", exc)
        return video_id

    def comment(self, video_id, text):
        """Add a top-level comment from the channel (pin it in YouTube Studio; the API can't)."""
        if self.dry_run:
            log.info("[DRY_RUN] YouTube comment on %s", video_id)
            return
        self._call("comment", self.yt.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}))

    def delete(self, video_id):
        self._call("delete", self.yt.videos().delete(id=video_id))

    def permalink(self, video_id, short=True):
        if not video_id or self.dry_run:
            return ""
        return ("https://www.youtube.com/shorts/" if short else "https://www.youtube.com/watch?v=") + video_id


def parse_caption(text):
    """-youtube.txt has TITLE / DESCRIPTION / PINNED COMMENT sections -> (title, description, pinned)."""
    sections, cur = {}, None
    for line in (text or "").splitlines():
        key = line.strip().upper()
        if key in ("TITLE", "DESCRIPTION", "PINNED COMMENT"):
            cur = key
            sections[cur] = []
        elif cur:
            sections[cur].append(line)
    get = lambda k: "\n".join(sections.get(k, [])).strip()
    if not sections:   # no headings: first line is the title, the rest the description
        lines = (text or "").strip().splitlines()
        return (lines[0] if lines else ""), "\n".join(lines[1:]).strip(), ""
    return get("TITLE"), get("DESCRIPTION"), get("PINNED COMMENT")
