"""Tell Meta to send your account's comments and DMs to the webhook.

Run once after the webhook URL is verified in the Meta app dashboard.
"""
from ig_api import InstagramClient, InstagramError

try:
    print(InstagramClient(dry_run=False).subscribe_webhooks())
    print("Subscribed. New comments and DMs will now reach your webhook.")
except InstagramError as exc:
    raise SystemExit("Subscribe failed: {}".format(exc))
