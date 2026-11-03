#!/bin/bash
# Installs (or with --remove, uninstalls) a Mac background job that runs
# auto_import.py whenever the Schedule folder changes, and once an hour.
#
#   ./install_auto_import.sh            install / update
#   ./install_auto_import.sh --remove   uninstall
set -euo pipefail

LABEL="com.insta-autopilot.auto-import"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(cd "$(dirname "$0")" && pwd)"
SCHEDULE_DIR="${SCHEDULE_DIR:-/Users/Sameer/soical media/Schedule}"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "Auto-import removed."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>-W</string><string>ignore</string>
    <string>$DIR/auto_import.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>SCHEDULE_DIR</key><string>$SCHEDULE_DIR</string>
  </dict>
  <!-- Run when anything in the Schedule folder changes... -->
  <key>WatchPaths</key><array><string>$SCHEDULE_DIR</string></array>
  <!-- ...and every hour, and at login, in case a change was missed. -->
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <!-- Run at most once a minute, even if many files change at once. -->
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$DIR/auto_import.launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/auto_import.launchd.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Auto-import installed. It watches: $SCHEDULE_DIR"
echo "Log: $DIR/auto_import.log"
