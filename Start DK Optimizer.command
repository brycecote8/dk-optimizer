#!/bin/bash
# Double-click this file to launch the optimizer web app.
# It moves into this folder and starts the app; your browser opens automatically.
cd "$(dirname "$0")"
HERE="$(pwd)"

# Closing the browser tab does NOT stop the app, so an old copy can keep
# running with old code. Stop any previous copy of THIS app (only ones started
# from this folder) so every launch is guaranteed to be the latest version.
for pid in $(pgrep -f "streamlit run app.py"); do
    dir="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    [ "$dir" = "$HERE" ] && kill "$pid" 2>/dev/null
done
sleep 1

echo "Starting the DraftKings Optimizer..."
echo "A browser tab will open. To STOP the app later, close this window."
echo ""
./venv/bin/streamlit run app.py
