#!/bin/bash
cd "$(dirname "$0")"
PORT=8765
open "http://localhost:$PORT/Mint%20Scout.html"
if python3 -c "import flask" 2>/dev/null; then
  # Runs the app through the Flask proxy (server.py) so Google Calendar sync and address
  # geocoding go through the server instead of the browser — avoids CORS/rate-limit issues.
  PORT=$PORT python3 server.py
else
  echo "Flask isn't installed, so Calendar sync and Nearby search may be less reliable."
  echo "For full reliability, run once: pip3 install -r requirements.txt"
  python3 -m http.server $PORT
fi
