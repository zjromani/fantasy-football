#!/bin/bash
# Uninstall fantasy football scheduled tasks

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "Uninstalling launchd jobs..."

for job in com.fantasy.ai-morning com.fantasy.ai-tuesday com.fantasy.ai-gameday; do
    plist="$LAUNCH_AGENTS/$job.plist"
    if [ -f "$plist" ]; then
        launchctl unload "$plist" 2>/dev/null
        rm "$plist"
        echo "  Removed: $job"
    fi
done

echo "Done!"
