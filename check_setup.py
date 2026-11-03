"""Quick test that your token works and finds your Instagram account id."""
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
