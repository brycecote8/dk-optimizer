#!/bin/bash
# Double-click this file to launch the optimizer web app.
# It moves into this folder and starts the app; your browser opens automatically.
cd "$(dirname "$0")"
echo "Starting the DraftKings Optimizer..."
echo "A browser tab will open. To STOP the app later, close this window."
echo ""
./venv/bin/streamlit run app.py
