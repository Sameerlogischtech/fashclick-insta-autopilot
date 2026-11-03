# Insta Autopilot

Free, self-hosted replacement for paid Instagram tools. It uses only the **official Instagram API**, so your password is never shared and the account stays safe.

| Script | What it does |
|---|---|
| `content.py` | Schedules reels, photo posts, carousels and stories. The cloud posts them on time, even with your Mac off. |
| `post_reel.py` | Posts one reel right now from your Mac |
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

## 4. Schedule reels, posts, carousels and stories

Schedule from your Mac. GitHub Actions posts them on time (checked every 5 minutes), even while your Mac is off.

```bash
# Reel: caption comes from reels/saree.txt next to the video
.venv/bin/python content.py add reels/saree.mp4 --at "2026-11-05 18:00"

# Photo post
.venv/bin/python content.py add look.jpg --caption "New kurti drop ✨ Comment KURTI" --at "tomorrow 10:00"

# Carousel: 2-10 photos/videos, in this order
.venv/bin/python content.py add 1.jpg 2.jpg 3.jpg --caption "Swipe for all 3 looks" --at "2026-11-06 19:30"

# Story: photo or video, no caption
.venv/bin/python content.py add story.mp4 --type story --at "2026-11-05 20:00"

# Post as soon as possible
.venv/bin/python content.py add reels/saree.mp4 --at now

.venv/bin/python content.py list            # what's scheduled, posted or failed (+ links)
.venv/bin/python content.py remove ab12cd   # unschedule
.venv/bin/python content.py retry ab12cd    # try a failed one again
```

Each `add` encrypts the files and caption, saves them in `content/`, and pushes to GitHub. Times are in your Mac's time zone.

**Privacy:** upcoming posts are stored **encrypted** with `CONTENT_KEY`, so nobody can see them in the public repo before they go live. Photos are copied to `published/` (public) only at the moment they're posted, because Instagram has to download them from a public link. Videos upload straight to Instagram.

**One-time setup:** the first `add` creates `CONTENT_KEY` in `.env`. Copy it to GitHub so the cloud can decrypt:

```bash
gh secret set CONTENT_KEY --body "$(grep ^CONTENT_KEY= .env | cut -d= -f2-)"
```

Keep `.env` safe. Without `CONTENT_KEY`, scheduled posts can't be read.

**Requirements**
- Reels: MP4/MOV, 9:16 (1080×1920), 3 s–15 min. Each file under 95 MB (GitHub's limit).
- Photos and carousels: any JPG/PNG/WebP, converted to JPEG automatically. Shape between 4:5 portrait (1080×1350) and 1.91:1 landscape. The tool refuses others.
- Captions: up to 2,200 characters and 30 hashtags. Put `Comment KEYWORD` in the caption to switch on auto-replies for that post.
- Stories: no captions, and **link stickers, polls and music can't be added through the API**. Add those in the Instagram app if you need them.

**Check on it:** GitHub → **Actions → Publish scheduled content**, or `content.py list` (run `git pull` first to get the latest status).

### Post one reel right now (from your Mac)

```bash
.venv/bin/python post_reel.py reels/day1.mp4   # caption from reels/day1.txt
```

## 5. Auto-reply to comments and DMs

### A different keyword on every reel (automatic)

Write the keyword in **CAPITALS** after the word "Comment" in the reel's caption:

> Comment **SHOOT** and I'll DM you the link

The bot reads each reel's caption and answers only that reel's keyword, in any letter case ("shoot", "Shoot!", "SHOOT please"). You change nothing when you post a new reel.
- Works: `Comment SHOOT`, `comment "PRICE"`, `Comment “SAREE2” below`
- Ignored (no capitals): `comment below`, `drop a comment`

Each person gets **one** DM per reel, even if they comment twice.

**Why two steps:** Instagram makes links in a first message from a business unclickable until the person accepts the chat. So the first DM asks them to reply **LINK**. Their reply accepts the chat, and the bot answers with the tappable fashclick.io link (`dm_rules` → "link request").

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
- Your Mac must be awake. For replies with your Mac off, use the cloud setup in section 7 instead.

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

`.github/workflows/autoreply.yml` runs `poller.py --once` every 5 minutes on GitHub's servers, so replies keep going while your Mac is off.

- Secrets live in **repo → Settings → Secrets and variables → Actions**: `IG_ACCESS_TOKEN`, `IG_USER_ID`, `IG_APP_SECRET`. They are never in the code.
- The memory of answered comments is kept in the Actions cache, which isn't visible to the public.
- Run logs are public, so the workflow sets `QUIET_LOGS=true`: logs show only counts and rule names, never usernames or comment text.
- **Run it now:** repo → **Actions → Instagram auto-reply → Run workflow**.
- **See what it did:** open any run under **Actions** and read the "Check comments and DMs" step.
- GitHub may start a scheduled run a few minutes late. Replies usually arrive within 5–15 minutes. Actions minutes are free on a public repo.
- If the repo has no new commits for 60 days, GitHub pauses scheduled workflows and emails you. Click **Enable workflow** in the Actions tab to resume.

⚠️ **Don't also run `poller.py` on your Mac** while the cloud one is on. They keep separate memories, so both would answer the same comment.

To change replies or the link, edit `rules.json`, then commit and push. The next run uses it.

## 8. Several brands (FashClick, VaaniCraft, VrittOS)

Each brand has its own folder in `accounts/<brand>/rules.json` (keyword replies and links) and its own queue in `content/<brand>/`. Add `--account <brand>` to any command. Without it, the command uses fashclick.

```bash
.venv/bin/python import_schedule.py "<schedule.json>" --account vaanicraft --apply
.venv/bin/python content.py list --account vrittos
.venv/bin/python check_setup.py --account vaanicraft
```

Settings per brand (in `.env` and as GitHub secrets; NAME in capitals):
- `IG_USER_ID_VAANICRAFT`, `IG_USER_ID_VRITTOS`: each brand's Instagram account id. FashClick keeps using `IG_USER_ID`.
- `IG_ACCESS_TOKEN_<NAME>`: only if that brand needs its own token. Otherwise the shared `IG_ACCESS_TOKEN` is used.

Both workflows run every brand side by side. A brand whose `IG_USER_ID_…` secret isn't set is skipped. To add a brand: create `accounts/<brand>/rules.json`, add it to the `matrix` in both workflow files, and add its secrets.

## 9. New weeks import automatically

A Mac background job runs `auto_import.py` whenever something changes in `soical media/Schedule/`, and once an hour. For every schedule file whose week has not ended, it imports all set-up brands. Items already queued or in the past are skipped. You get a Mac notification when posts are queued, or when an item has a problem (for example a missing file or a wrong photo shape). Details go to `auto_import.log`. Fix the problem and it is picked up on the next run.

```bash
./install_auto_import.sh            # install
./install_auto_import.sh --remove   # turn it off
.venv/bin/python auto_import.py --dry-run   # preview
```

The Mac must be on when the schedule file is added (or within the hour). Posting itself still happens in the cloud.

## 10. Facebook Pages

Every schedule row whose platforms include Facebook is also queued for the brand's Facebook Page, with the row's Facebook caption:
- reel → Facebook Reel
- carousel → one post with all the photos
- photo → photo post
- story → Facebook Story (no stickers)

Setup per brand:
1. Add the "Manage everything on your Page" use case to the brand's Meta app (`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `read_insights`).
2. Assign the Page to the brand's system user.
3. Generate a new token with the 4 `instagram_*` and these Page permissions. One token covers both.
4. Save the token, then run `check_setup.py --account <brand> --save` to store `FB_PAGE_ID[_BRAND]`. Upload `.env` with `gh secret set -f .env`.

A brand's Facebook stays off until its `FB_PAGE_ID` is set. Comment auto-replies are Instagram-only.

## 11. YouTube channels

Every schedule row marked "YouTube Short" (and every long `video` row) is also queued for the brand's YouTube channel. Title, description and pinned-comment text come from the row's `-youtube.txt` (TITLE / DESCRIPTION / PINNED COMMENT). Each upload is public and sets YouTube's "altered or synthetic content" flag. The pinned-comment text is posted as a comment; pin it in YouTube Studio, since the API can't. Community posts have no API and stay manual.

Setup (done once):
1. In Google Cloud project `insta-autopilot`, enable the YouTube Data API v3.
2. Set the OAuth app to External and publish it ("In production"), so sign-ins don't expire after 7 days. Leave the logo empty.
3. Create a Desktop OAuth client and save it as `youtube_client.json`. It is kept out of git.

Connect a channel (needs the channel **owner**; Studio editors can't authorize apps):
- You own it: `.venv/bin/python yt_auth.py --account <brand>` and pick the channel in Google's chooser.
- Someone else owns it:
  1. `yt_auth.py --account <brand> --link` prints a link for the owner.
  2. They sign in and send back the `http://localhost:1/?...code=...` address.
  3. Run `yt_auth.py --account <brand> --code '<that address>'`.

The code expires within minutes. Sign-in refuses to save if the channel name doesn't contain the brand. Afterwards, upload the keys with `gh secret set -f .env`.
