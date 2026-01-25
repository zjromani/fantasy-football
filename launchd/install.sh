#!/bin/bash
# Install fantasy football scheduled tasks

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "Installing launchd jobs..."

for plist in "$SCRIPT_DIR"/*.plist; do
    name=$(basename "$plist")
    dest="$LAUNCH_AGENTS/$name"

    # Unload if already loaded
    launchctl unload "$dest" 2>/dev/null

    # Copy and load
    cp "$plist" "$dest"
    launchctl load "$dest"

    echo "  Installed: $name"
done

echo ""
echo "Done! Jobs scheduled:"
echo "  - ai_morning: Daily at 7:00 AM"
echo "  - ai_tuesday: Tuesday at 6:00 AM"
echo "  - ai_gameday: Sunday at 10:00 AM"
echo ""
echo "Logs: $(dirname "$SCRIPT_DIR")/logs/"
echo ""
echo "To uninstall, run: ./launchd/uninstall.sh"
