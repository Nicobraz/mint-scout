#!/bin/bash
cd "$(dirname "$0")"
python3 apollo_bot.py &
sleep 0.8
osascript -e 'tell application "Terminal" to set miniaturized of front window to true' 2>/dev/null
wait
