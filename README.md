# Insta Autopilot

Free, self-hosted replacement for paid Instagram tools. It uses only the **official Instagram API**, so your password is never shared and the account stays safe.

| Script | What it does |
|---|---|
| `post_reel.py` | Posts one reel right now |
| `scheduler.py` | Posts reels from `queue.json` at the times you set |
| `poller.py` | Checks comments and DMs every minute and answers them using `rules.json`. **Works without publishing the Meta app.** |
| `webhook_server.py` | Same, but instant. Only works once the Meta app is published (Live) |
| `subscribe_webhooks.py` | Connects your account's comments and DMs to the webhook (run once) |
| `check_setup.py` | Confirms your token works |

---

## 1. Install

```bash
cd insta-autopilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Instagram account

In the Instagram app: **Settings → Account type and tools → Switch to professional account** (Creator or Business).

Also turn on: **Settings → Messages and story replies → Message requests → Connected tools → Allow access to messages.** Without it, DMs won't work.

## 3. Meta app and token (free, "Unified login")

New Meta apps only offer **"API setup with Unified login"**. It gives you a **system-user token that never expires**, so there's nothing to renew.

**A. Business portfolio** (skip if you have one)
1. Go to <https://business.facebook.com> and create a business portfolio.
2. Open **Settings → Accounts → Instagram accounts → Add** and connect your Instagram account.

**B. Meta app** (at <https://developers.facebook.com>)
1. Open your app → **Use cases → Instagram API → API setup with Unified login**.
2. Click **Create new configuration** and keep the defaults (General, System-user access token, Never expires). Tick all four Instagram permissions:
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`.
   The ad permissions aren't needed. Save.
3. Connect the app to your portfolio, if Meta asks: **App settings → Basic → Business portfolio**.

**C. System user and token** (back in business.facebook.com → **Settings**)
1. Go to **Users → System users → Add**. Give it any name, role **Admin**.
2. Click **Assign assets → Instagram accounts →** pick your account → turn on **Full control** → save.
3. Under **Apps**, add your Meta app with **Full control**.
4. Click **Generate token** → pick your app → expiry **Never** → tick the four `instagram_*` permissions → **Generate**. Copy the token now; Meta shows it only once.

**D. Fill in `.env`**
- the token → `IG_ACCESS_TOKEN`
- your Instagram account id → `IG_USER_ID`. It's shown in **Business settings → Accounts → Instagram accounts** when you click the account. `check_setup.py` also tries to find it.
- **App settings → Basic → App secret** (click Show) → `IG_APP_SECRET`
- any random word → `WEBHOOK_VERIFY_TOKEN`

Then test:

```bash
python check_setup.py
```

## 4. Post reels

Set `DRY_RUN=false` in `.env` to post for real. Leave it `true` to see what would happen without posting.

```bash
# Caption from a matching .txt file next to the video (reels/day1.txt)
python post_reel.py reels/day1.mp4

# Or give the caption directly
python post_reel.py reels/day1.mp4 --caption "Hook line... #tag"
```

Reel requirements: MP4 (H.264 + AAC), 9:16 vertical (1080×1920 is best), 3 seconds to 15 minutes, under 300 MB.

### Schedule a week of reels

```bash
cp queue.example.json queue.json   # edit videos, captions, times
python scheduler.py --loop         # leave running; checks every 5 min
```

Or without leaving a terminal open, run it from cron every 10 minutes (`crontab -e`):

```
*/10 * * * * cd /full/path/to/insta-autopilot && .venv/bin/python scheduler.py >> scheduler.log 2>&1
```

Your Mac must be awake at post time. Each item is marked `posted` or `failed` in `queue.json`, so nothing is posted twice.

## 5. Auto-reply to comments and DMs

### A different keyword on every reel (automatic)

Write the keyword in **CAPITALS** after the word "Comment" in the reel's caption:

> Comment **SHOOT** and I'll DM you the link

The bot reads each reel's caption and answers only that reel's keyword, in any letter case ("shoot", "Shoot!", "SHOOT please"). You change nothing when you post a new reel.
- Works: `Comment SHOOT`, `comment "PRICE"`, `Comment “SAREE2” below`
- Ignored (no capitals): `comment below`, `drop a comment`

Each person gets **one** DM per reel, even if they comment twice.

### Edit what it sends: **`rules.json`**
- `caption_keyword`: the public replies (one is picked at random) and the DM sent for caption keywords.
- `comment_rules`: optional fixed keywords that work on every post.
- `dm_rules`: if someone DMs a word (e.g. "price"), reply automatically.

Changes apply immediately. No restart is needed.

### Easiest: polling (no publishing, no server, no ngrok)

```bash
.venv/bin/python poller.py
```

Leave it running. Every 60 seconds it reads your last 10 posts' comments and your recent DMs, and answers new ones.
- It only answers comments made **after you start it**, so old comments never get a surprise reply. Use `--since 3h` to include the last 3 hours.
- It remembers what it already answered (in `state.json`), so restarting never double-replies.
- Your Mac must be awake. To keep it running in the background, see the cron/launchd tip under "Schedule a week of reels".

### Instant replies: webhook (needs the Meta app published)

Meta only pushes comment and DM events to apps that are **Live**, and publishing needs **Business Verification**. Until then, use the poller.

### Put the webhook online (free)

Instagram has to reach your server over HTTPS. Pick one:

**A. Render.com (free, always online):**
push this folder to a private GitHub repo → Render → **New Web Service** → connect the repo.
Build command: `pip install -r requirements.txt`. Start command: `gunicorn webhook_server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`.
Add the `.env` values under **Environment**.
Note: free Render services sleep when idle. The first comment after a quiet period is answered about a minute late, because Meta retries.

**B. Your own Mac (free, only while it's on):**

```bash
python webhook_server.py              # terminal 1
brew install cloudflared
cloudflared tunnel --url http://localhost:8000   # terminal 2, prints an https URL
```

### Connect it to Instagram

In the Meta app → **Use cases → Instagram API → Webhooks**:
- Callback URL: `https://YOUR-URL/webhook`
- Verify token: the same word as `WEBHOOK_VERIFY_TOKEN`
- Click **Verify and save**, then subscribe to **comments** and **messages**.

Then run this once, so Meta sends your account's events to the app:

```bash
python subscribe_webhooks.py
```

If DMs fail with an "unsupported" error, put your Facebook Page id in `IG_MESSAGING_ID` in `.env`. Meta's newest setup is still changing, so this fallback is there just in case.

### ⚠️ Webhook note

**Posting** works right away for your own account.
Comments and DMs from **other people** only reach your webhook once the app is in **Live mode** with **Advanced Access** for `instagram_business_manage_comments` and `instagram_business_manage_messages`. That means submitting the app for **App Review**. It's free, but it takes a few days. Meta asks for:
- a privacy policy URL (a simple page is fine)
- a short screen recording showing the auto-reply working
- sometimes **Business Verification**

Until then, test with comments and DMs from accounts added as testers in **App roles**.

## 6. Token expiry

A system-user token set to **Never** doesn't expire, so you can skip this.
`refresh_token.py` is only for older apps that use "Instagram login" (`GRAPH_HOST=graph.instagram.com`); their tokens last 60 days.

## Safety limits (stay well under these)

- At most 25 posts per day via the API. 1–3 reels a day is normal.
- At most 200 automated DMs per hour.
- Only DM people who commented or messaged you first. The code already enforces this.

## 7. Run 24/7 in the cloud (GitHub Actions, free)

`.github/workflows/autoreply.yml` runs `poller.py --once` every 30 minutes on GitHub's servers, so replies keep going while your Mac is off.

- Secrets live in **repo → Settings → Secrets and variables → Actions**: `IG_ACCESS_TOKEN`, `IG_USER_ID`, `IG_APP_SECRET`. They are never in the code.
- The memory of answered comments is kept in the Actions cache, which isn't visible to the public.
- **Run it now:** repo → **Actions → Instagram auto-reply → Run workflow**.
- **See what it did:** open any run under **Actions** and read the "Check comments and DMs" step.
- GitHub may start a scheduled run a few minutes late. Replies usually arrive within 30–40 minutes. Each run uses about 1 of the 2,000 free private-repo minutes per month (about 1,440 used).
- If the repo has no new commits for 60 days, GitHub pauses scheduled workflows and emails you. Click **Enable workflow** in the Actions tab to resume.

⚠️ **Don't also run `poller.py` on your Mac** while the cloud one is on. They keep separate memories, so both would answer the same comment.

To change replies or the link, edit `rules.json`, then commit and push. The next run uses it.
