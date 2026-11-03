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


def remote_sign_in(InstalledAppFlow):
    """For a channel owned by someone else: they sign in on their own device from a link.

    Google then sends their browser to http://localhost:1/?code=..., which doesn't load on their
    device; they copy that address and send it back. The code in it is single-use, expires in a few
    minutes, and is useless without this folder's youtube_client.json.
    """
    import os
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")   # the loopback redirect is plain http
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES, redirect_uri="http://localhost:1")
    url, _ = flow.authorization_url(prompt="select_account consent", access_type="offline")
    print("\nSend this link to the channel owner:\n\n" + url + "\n")
    print("Tell them: open it, sign in, pick the {} channel, click 'Advanced' -> 'Go to Content Autopilot',\n"
          "allow everything. Their browser will then say the page can't be reached. That's expected:\n"
          "they copy the whole address from the address bar and send it back to you.\n".format(config.ACCOUNT))
    answer = input("Paste the address they sent (starts with http://localhost:1/?): ").strip()
    if "code=" not in answer:
        sys.exit("That doesn't contain a sign-in code. Run this again and ask for the full address.")
    flow.fetch_token(authorization_response=answer.replace("https://", "http://", 1))
    return flow.credentials


def pending_file():
    return config.BASE_DIR / ".yt_pending_{}.json".format(config.ACCOUNT)


def make_link(InstalledAppFlow):
    """Step 1 of the two-step remote sign-in: print the link and remember its PKCE verifier."""
    import os
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES, redirect_uri="http://localhost:1")
    url, state = flow.authorization_url(prompt="select_account consent", access_type="offline")
    pending_file().write_text(json.dumps({"code_verifier": flow.code_verifier, "state": state}))
    pending_file().chmod(0o600)
    print(url)


def finish_link(InstalledAppFlow, answer):
    """Step 2: exchange the address the owner sent back."""
    import os
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    if not pending_file().exists():
        sys.exit("No link was made for {} yet. Run with --link first.".format(config.ACCOUNT))
    saved = json.loads(pending_file().read_text())
    if "code=" not in answer:
        sys.exit("That doesn't contain a sign-in code.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES, redirect_uri="http://localhost:1",
                                                     state=saved["state"], code_verifier=saved["code_verifier"],
                                                     autogenerate_code_verifier=False)
    flow.fetch_token(authorization_response=answer.strip().replace("https://", "http://", 1))
    pending_file().unlink()
    return flow.credentials


def main():
    if not CLIENT_FILE.exists():
        sys.exit("Put the downloaded OAuth client file here as youtube_client.json first.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    if "--link" in sys.argv:
        return make_link(InstalledAppFlow)
    if "--code" in sys.argv:
        creds = finish_link(InstalledAppFlow, sys.argv[sys.argv.index("--code") + 1])
    elif "--remote" in sys.argv:
        creds = remote_sign_in(InstalledAppFlow)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        print("A browser window will open. Sign in and choose the {} YouTube channel.".format(config.ACCOUNT))
        # select_account: always show Google's account / brand-channel chooser instead of reusing the last pick.
        creds = flow.run_local_server(port=0, prompt="select_account consent", access_type="offline",
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
