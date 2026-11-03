"""Extend your long-lived token by 60 days and save it back into .env.

Run it every few weeks (or from cron weekly). The token must be at least
24 hours old and not yet expired.
"""
import logging
import re

import config
from ig_api import InstagramClient, InstagramError


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        data = InstagramClient().refresh_token()
    except InstagramError as exc:
        raise SystemExit(str(exc))
    new_token = data["access_token"]
    if config.DRY_RUN:
        print("DRY_RUN: token not changed")
        return

    env = config.ENV_FILE.read_text(encoding="utf-8")
    env = re.sub(r"^IG_ACCESS_TOKEN=.*$", "IG_ACCESS_TOKEN=" + new_token, env, flags=re.M)
    config.ENV_FILE.write_text(env, encoding="utf-8")
    days = int(data.get("expires_in", 0)) // 86400
    print("Token refreshed and saved to .env, valid for about {} days.".format(days))
    print("If the webhook runs on a host (Render/Railway), paste the new token into its env vars too.")


if __name__ == "__main__":
    main()
