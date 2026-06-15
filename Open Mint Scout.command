#!/bin/bash
cd "$(dirname "$0")"
PORT=8765
open "http://localhost:$PORT/Mint%20Scout.html"
python3 -m http.server $PORT
