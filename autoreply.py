"""Shared reply logic for comments and DMs, used by both the webhook server
and the poller, so the two never disagree about what to send.
"""
import json
import logging
import random
import re
import threading

import config
from ig_api import InstagramClient, InstagramError

log = logging.getLogger("autoreply")

client = InstagramClient()
_state_lock = threading.Lock()


def load_rules():
    # Read on every event so edits to rules.json apply without a restart.
    return json.loads(config.RULES_FILE.read_text(encoding="utf-8"))


def load_state():
    state = {}
    if config.STATE_FILE.exists():
        state = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    for key in ("handled_comments", "dmed_user_media", "handled_messages"):
        state.setdefault(key, [])
    return state


def save_state(state):
    # Keep the file small: only the most recent ids matter for de-duplication.
    for key, value in state.items():
        if isinstance(value, list):
            state[key] = value[-5000:]
    config.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def update_state(fn):
    with _state_lock:
        state = load_state()
        result = fn(state)
        save_state(state)
        return result


def matches(text, keywords):
    text = (text or "").lower()
    return any(re.search(r"\b{}\b".format(re.escape(k.lower())), text) for k in keywords)


def find_rule(rules, text):
    for rule in rules:
        if matches(text, rule.get("keywords", [])):
            return rule
    return None


# "Comment SHOOT and I'll DM you..." -> SHOOT. The keyword must be in capitals,
# so ordinary phrases like "comment below" are never mistaken for one.
CAPTION_KEYWORD = re.compile(r"(?i:\bcomment)\s+[\"'“”‘’]?([A-Z][A-Z0-9]+)\b")
_caption_cache = {}


def caption_keyword(media_id, caption=None):
    if media_id not in _caption_cache:
        if caption is None:
            try:
                caption = client.media_caption(media_id)
            except InstagramError as exc:
                log.error("Couldn't read caption of %s: %s", media_id, exc)
                return None
        m = CAPTION_KEYWORD.search(caption or "")
        _caption_cache[media_id] = m.group(1) if m else None
    return _caption_cache[media_id]


def pick_comment_rule(rules, media_id, text, caption=None):
    """The reel's own caption keyword wins; then fixed comment_rules; then the default."""
    settings = rules.get("caption_keyword") or {}
    if settings.get("enabled", True):
        keyword = caption_keyword(media_id, caption)
        if keyword and matches(text, [keyword]):
            return dict(settings, name="caption keyword " + keyword)
    return find_rule(rules.get("comment_rules", []), text) or rules.get("comment_default") or {}


def handle_comment(value):
    """value: {"id", "text", "from": {"id", "username"}, "media": {"id", "caption"?}}"""
    comment_id = value.get("id")
    sender = value.get("from", {})
    media_id = value.get("media", {}).get("id", "")
    caption = value.get("media", {}).get("caption")
    text = value.get("text", "")

    # Never answer ourselves, or we'd loop on our own public replies.
    if not comment_id or sender.get("id") == config.IG_USER_ID:
        return False

    user_media = "{}:{}".format(sender.get("id"), media_id)

    def claim(state):
        if comment_id in state["handled_comments"]:
            return None
        state["handled_comments"].append(comment_id)
        return user_media in state["dmed_user_media"]

    already_dmed = update_state(claim)
    if already_dmed is None:
        return False

    rule = pick_comment_rule(load_rules(), media_id, text, caption)
    if config.QUIET_LOGS:
        log.info("New comment -> rule %s", rule.get("name", "default"))
    else:
        log.info("Comment from @%s: %r -> rule %s", sender.get("username"), text, rule.get("name", "default"))

    replies = rule.get("public_replies") or []
    dm = rule.get("dm")
    if not (replies or dm):
        return False
    try:
        if replies:
            client.reply_to_comment(comment_id, random.choice(replies))
        # One DM per person per reel, even if they comment the keyword twice.
        if dm and not already_dmed:
            client.private_reply(comment_id, dm)
            update_state(lambda s: s["dmed_user_media"].append(user_media))
    except InstagramError as exc:
        log.error("Comment %s: %s", comment_id, exc)
        return False
    return True


def handle_message(event):
    """event: {"sender": {"id"}, "message": {"mid", "text", "is_echo"?}}"""
    message = event.get("message", {})
    sender_id = event.get("sender", {}).get("id")
    mid = message.get("mid")

    # Echoes are copies of messages we sent; skip them and our own id.
    if message.get("is_echo") or not mid or sender_id == config.IG_USER_ID:
        return False

    def claim(state):
        if mid in state["handled_messages"]:
            return False
        state["handled_messages"].append(mid)
        return True

    if not update_state(claim):
        return False

    rules = load_rules()
    rule = find_rule(rules.get("dm_rules", []), message.get("text", ""))
    reply = rule["reply"] if rule else rules.get("dm_default")
    name = rule["name"] if rule else "default"
    if config.QUIET_LOGS:
        log.info("New DM -> %s", name)
    else:
        log.info("DM from %s: %r -> %s", sender_id, message.get("text"), name)
    if not reply:
        return False
    try:
        client.send_dm(sender_id, reply)
    except InstagramError as exc:
        log.error("DM %s: %s", mid, exc)
        return False
    return True


def process(payload):
    """Handle one webhook payload from Meta."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") in ("comments", "live_comments"):
                handle_comment(change.get("value", {}))
        for event in entry.get("messaging", []):
            if "message" in event:
                handle_message(event)
