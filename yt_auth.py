"""One-time Google sign-in that connects a brand's YouTube channel.

    .venv/bin/python yt_auth.py --account fashclick

Needs youtube_client.json (the OAuth "Desktop app" client from Google Cloud) in
this folder. A browser opens: sign in and pick THIS brand's channel. The refresh
token is saved in .env as YT_REFRESH_TOKEN (fashclick) or YT_REFRESH_TOKEN_<BRAND>,
together with YT_CLIENT_ID / YT_CLIENT_SECRET. No password is stored.
"""
import json
import re
import sys

import config
from yt_api import SCOPES

CLIENT_FILE = config.BASE_DIR / "youtube_client.json"


def save(env_updates):
    env = config.ENV_FILE.read_text(encoding="utf-8")
    for k, v in env_updates.items():
        line = "{}={}".format(k, v)
        if re.search(r"^{}=".format(k), env, re.M):
            env = re.sub(r"^{}=.*$".format(k), line, env, flags=re.M)
        else:
            env = env.rstrip("\n") + "\n" + line + "\n"
    config.ENV_FILE.write_text(env, encoding="utf-8")


def main():
    if not CLIENT_FILE.exists():
        sys.exit("Put the downloaded OAuth client file here as youtube_client.json first.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    print("A browser window will open. Sign in and choose the {} YouTube channel.".format(config.ACCOUNT))
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline",
                                  authorization_prompt_message="", success_message=
                                  "Connected. You can close this tab and go back to Claude.")
    if not creds.refresh_token:
        sys.exit("Google didn't return a refresh token. Run this again.")
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    channel = items[0]["snippet"]["title"] if items else "(no channel found)"
    # Guard against picking the wrong channel (e.g. a personal one): the name must contain the brand.
    if config.ACCOUNT.lower() not in channel.lower().replace(" ", "") and "--force" not in sys.argv:
        sys.exit("That sign-in chose the channel {!r}, not {}'s. Nothing was saved.\n"
                 "Run again and pick the {} channel (if it isn't offered, choose 'Use another account' and sign in "
                 "with the Google account that owns it). Add --force only if the name really is right."
                 .format(channel, config.ACCOUNT, config.ACCOUNT))
    client = json.loads(CLIENT_FILE.read_text())
    client = client.get("installed") or client.get("web") or {}
    key = "YT_REFRESH_TOKEN" if config.ACCOUNT == "fashclick" else "YT_REFRESH_TOKEN_" + config.ACCOUNT.upper()
    save({"YT_CLIENT_ID": client["client_id"], "YT_CLIENT_SECRET": client["client_secret"], key: creds.refresh_token})
    print("Connected {} to the YouTube channel: {}".format(config.ACCOUNT, channel))
    print("Saved {} in .env.".format(key))


if __name__ == "__main__":
    main()
