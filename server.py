#!/usr/bin/env python3
"""
Mint Scout web server.
Serves the HTML app and proxies /apollo/* to Apollo's API server-side
so the browser never has to deal with CORS or API keys.
"""

import json
import os
import urllib.request
import urllib.error
from flask import Flask, request, Response, send_file

app = Flask(__name__)
APOLLO_BASE = "https://api.apollo.io/api/v1/"
HTML_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Mint Scout.html")


def apollo_key():
    return os.environ.get("APOLLO_API_KEY", "")


@app.route("/")
def index():
    return send_file(HTML_FILE)


@app.route("/fetch")
def fetch_proxy():
    url = request.args.get("url", "")
    if not url:
        return Response("Missing url param", status=400)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "text/plain")
            return Response(resp.read(), status=200, headers={
                "Content-Type": content_type,
                "Access-Control-Allow-Origin": "*",
            })
    except Exception as ex:
        return Response(str(ex), status=500, headers={"Access-Control-Allow-Origin": "*"})


@app.route("/apollo/<path:path>", methods=["GET", "POST", "OPTIONS"])
def apollo_proxy(path):
    if request.method == "OPTIONS":
        return Response("", 200, {
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    key = apollo_key()
    if not key:
        return Response(
            json.dumps({"error": "APOLLO_API_KEY not set on server"}),
            status=500, mimetype="application/json"
        )

    url  = APOLLO_BASE + path
    data = request.get_data() if request.method == "POST" else None
    req  = urllib.request.Request(url, data=data, method=request.method, headers={
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-Api-Key":    key,
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return Response(resp.read(), status=resp.status, mimetype="application/json")
    except urllib.error.HTTPError as e:
        return Response(e.read(), status=e.code, mimetype="application/json")
    except Exception as ex:
        return Response(json.dumps({"error": str(ex)}), status=500, mimetype="application/json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
