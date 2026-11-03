"""Queue every brand's Instagram posts from new schedule files, automatically.

Run by a Mac background job (see install_auto_import.sh) whenever something
changes in the Schedule folder, and once an hour as a safety net:

    python auto_import.py            # import all upcoming schedule files
    python auto_import.py --dry-run  # only show what would be queued

Already-queued and past items are skipped, so it's safe to run any time.
Shows a Mac notification when it queued something or hit a problem; details
go to auto_import.log.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import config

SCHEDULE_DIR = Path(os.getenv("SCHEDULE_DIR", "/Users/Sameer/soical media/Schedule"))
LOG_FILE = config.BASE_DIR / "auto_import.log"
LAST_ALERT_FILE = config.BASE_DIR / ".auto_import_last_alert"
PYTHON = sys.executable


def log(msg):
    line = "{} {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def notify(title, text):
    script = 'display notification {} with title {}'.format(json.dumps(text), json.dumps(title))
    subprocess.run(["osascript", "-e", script], capture_output=True)


def configured_accounts():
    """Brands that have an Instagram id set up; others are skipped."""
    found = []
    for account in config.ACCOUNTS:
        key = "IG_USER_ID_" + account.upper()
        if os.getenv(key) or (account == "fashclick" and os.getenv("IG_USER_ID")):
            found.append(account)
    return found


def upcoming_schedules():
    """Schedule files whose week hasn't ended yet (by the dates in the file name)."""
    today = date.today()
    for path in sorted(SCHEDULE_DIR.glob("*_schedule.json")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})", path.name)
        if m and date.fromisoformat(m.group(2)) < today:
            continue
        yield path


def main():
    parser = argparse.ArgumentParser(description="Auto-import new schedule files for all brands")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; queue nothing")
    args = parser.parse_args()

    # Only one import at a time (the folder watcher can fire several times in a row).
    lock = open(config.BASE_DIR / ".auto_import.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    # Get the cloud's latest "posted" records first, so pushes don't clash.
    subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], cwd=config.BASE_DIR,
                   capture_output=True)

    totals, problems = {}, []
    for schedule in upcoming_schedules():
        for account in configured_accounts():
            cmd = [PYTHON, "-W", "ignore", "import_schedule.py", str(schedule), "--account", account]
            if not args.dry_run:
                cmd.append("--apply")
            out = subprocess.run(cmd, cwd=config.BASE_DIR, capture_output=True, text=True)
            lines = (out.stdout + out.stderr).splitlines()
            queued = sum(1 for l in lines if l.startswith(("QUEUE ", "would queue")))
            errors = [l for l in lines if l.startswith("ERROR")]
            if out.returncode not in (0, 2):   # crashed, not just item errors
                errors.append("ERROR import crashed: " + (lines[-1] if lines else "no output"))
            if queued or errors:
                log("{} [{}] {} {}, {} problem(s)".format(schedule.name, account,
                    "would queue" if args.dry_run else "queued", queued, len(errors)))
                for e in errors:
                    log("   " + e)
            totals[account] = totals.get(account, 0) + queued
            problems += ["{}: {}".format(account, e[6:].strip()) for e in errors]

    queued_total = sum(totals.values())
    if args.dry_run:
        print("Would queue:", totals or "nothing", "| problems:", len(problems))
        return
    if queued_total:
        summary = ", ".join("{} {}".format(a, n) for a, n in totals.items() if n)
        notify("Instagram autopilot", "Queued {} posts ({})".format(queued_total, summary))
    # Alert about problems once, not every hour while they're unfixed.
    signature = "\n".join(sorted(problems))
    last = LAST_ALERT_FILE.read_text() if LAST_ALERT_FILE.exists() else ""
    if problems and signature != last:
        notify("Instagram autopilot: {} problem(s)".format(len(problems)),
               problems[0][:120] + ("  (+{} more, see auto_import.log)".format(len(problems) - 1)
                                    if len(problems) > 1 else ""))
    LAST_ALERT_FILE.write_text(signature)


if __name__ == "__main__":
    main()
