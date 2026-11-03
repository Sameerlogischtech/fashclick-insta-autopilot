"""Quick test that your token works and finds your Instagram account and Facebook Page ids.

    python check_setup.py --account vaanicraft [--save]
"""
import sys
import config
from ig_api import InstagramClient, InstagramError

if not config.IG_ACCESS_TOKEN or config.IG_ACCESS_TOKEN.startswith("paste-"):
    raise SystemExit("Put your token in .env as IG_ACCESS_TOKEN first.")

client = InstagramClient(dry_run=False, user_id=config.IG_USER_ID or "unset")

try:
    owner = client.token_owner()
    print("Token works. It belongs to: {} (id {})".format(owner.get("name"), owner.get("id")))
except InstagramError as exc:
    raise SystemExit("Token problem: {}".format(exc))

if config.IG_USER_ID and not config.IG_USER_ID.startswith("paste-"):
    try:
        acct = client.account()
        print("Connected to Instagram @{} (id {}). You're ready to post.".format(
            acct.get("username"), acct.get("id")))
    except InstagramError as exc:
        print("IG_USER_ID {} didn't work: {}".format(config.IG_USER_ID, exc))
        print("Make sure the Instagram account is assigned to the system user, with full control.")
else:
    print("IG_USER_ID is not set yet. Looking for Instagram accounts this token can reach...")
    try:
        found = client.find_instagram_accounts()
    except InstagramError as exc:
        found = []
        print("  (lookup through Pages not available: {})".format(exc))
    for source, ig in found:
        print("  @{} -> IG_USER_ID={}  ({})".format(ig.get("username"), ig.get("id"), source))
    if not found:
        print("  None found automatically. Copy the id from Business settings ->"
              " Accounts -> Instagram accounts, and put it in .env as IG_USER_ID.")


# ---------- Facebook Page ----------
import re
from fb_api import FacebookClient
print()
if config.FB_PAGE_ID:
    try:
        info = FacebookClient(dry_run=False).page_info()
        print("Facebook Page: {} (id {}) · {} followers. Ready to post.".format(info.get("name"), info.get("id"), info.get("followers_count")))
    except InstagramError as exc:
        print("FB_PAGE_ID {} didn't work: {}".format(config.FB_PAGE_ID, exc))
else:
    import requests
    r = requests.get("https://graph.facebook.com/{}/me/accounts".format(config.GRAPH_API_VERSION),
                     params={"fields": "id,name,tasks", "access_token": config.IG_ACCESS_TOKEN}).json()
    pages = r.get("data", [])
    if not pages:
        print("No Facebook Page reachable yet ({}).".format(r.get("error", {}).get("message", "none assigned")[:120]))
        print("Assign the Page to the system user and add the pages_* permissions to the token.")
    else:
        key = "FB_PAGE_ID" if config.ACCOUNT == "fashclick" else "FB_PAGE_ID_" + config.ACCOUNT.upper()
        for pg in pages:
            print("Facebook Page found: {} (id {})".format(pg["name"], pg["id"]))
        if len(pages) == 1 and "--save" in sys.argv:
            env = config.ENV_FILE.read_text()
            line = "{}={}".format(key, pages[0]["id"])
            env = re.sub(r"^{}=.*$".format(key), line, env, flags=re.M) if re.search(r"^{}=".format(key), env, re.M) else env.rstrip("\n") + "\n" + line + "\n"
            config.ENV_FILE.write_text(env)
            print("Saved {} in .env".format(line))
        else:
            print("Run again with --save to store it as {} in .env".format(key))
