#!/usr/bin/env python3
"""
Mint Scout → Apollo Bot
Runs as a local service on port 5005.
Mint Scout sends selected contacts here; the bot looks them up in Apollo
and adds matched ones to the chosen sequence automatically.
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5005
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apollo_config.json")
API_BASE = "https://api.apollo.io/api/v1"
GREEN  = "#1D9E75"
BG     = "#f8f9fa"
DARK   = "#1a1a1a"

_app = None  # global ref so HTTP handler can call into the GUI


# ── Config ───────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Apollo helpers ────────────────────────────────────────────────────────────

def apollo_post(path, body, api_key):
    url = f"{API_BASE}/{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-Api-Key":    api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:    return json.loads(e.read())
        except: return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silence access logs

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self._json({"ok": True, "sequence": _app.current_seq_name()})
        elif self.path == "/sequences":
            seqs = [{"id": s["id"], "name": s["name"], "active": s.get("active", False)}
                    for s in _app._sequences]
            self._json({"sequences": seqs})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/add":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            contacts = body.get("contacts", [])
            self._json({"received": len(contacts)})
            threading.Thread(target=_app.process_contacts, args=(contacts,), daemon=True).start()
        else:
            self.send_error(404)

    def _json(self, data):
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload)


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Apollo Bot")
        self.geometry("460x500")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._sequences        = []
        self._selected_seq_idx = 0
        self._api_key          = ""

        self._build_ui()
        self._load_config()

        threading.Thread(target=self._start_server, daemon=True).start()

        if self._api_key:
            self._key_var.set(self._api_key)
            self._fetch_sequences()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=GREEN, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Apollo Bot", font=("Helvetica", 15, "bold"),
                 bg=GREEN, fg="white").pack()
        tk.Label(hdr, text="Mint Scout integration", font=("Helvetica", 10),
                 bg=GREEN, fg="#bde8d8").pack()

        body = tk.Frame(self, bg=BG, padx=22)
        body.pack(fill=tk.BOTH, expand=True, pady=14)

        # Status row
        sr = tk.Frame(body, bg=BG)
        sr.pack(fill=tk.X, pady=(0, 14))
        tk.Label(sr, text="Status:", font=("Helvetica", 10, "bold"), bg=BG, fg=DARK).pack(side=tk.LEFT)
        self._dot = tk.Label(sr, text=" ●", font=("Helvetica", 13), bg=BG, fg="#ccc")
        self._dot.pack(side=tk.LEFT)
        self._status_lbl = tk.Label(sr, text="Starting…", font=("Helvetica", 10), bg=BG, fg="#888")
        self._status_lbl.pack(side=tk.LEFT, padx=4)

        # API key
        self._lbl("API Key", body)
        kr = tk.Frame(body, bg=BG)
        kr.pack(fill=tk.X, pady=(2, 14))
        self._key_var = tk.StringVar()
        tk.Entry(kr, textvariable=self._key_var, show="•", font=("Helvetica", 10),
                 relief="solid", bd=1, bg="white").pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0,8))
        tk.Button(kr, text="Connect", command=self._connect,
                  bg=GREEN, fg="white", font=("Helvetica", 10), bd=0, padx=10, pady=5, cursor="hand2").pack(side=tk.LEFT)

        # Sequence
        self._lbl("Active Sequence", body)
        self._seq_var = tk.StringVar(value="Enter API key to load sequences…")
        self._combo = ttk.Combobox(body, textvariable=self._seq_var, state="disabled", font=("Helvetica", 10))
        self._combo.pack(fill=tk.X, ipady=4, pady=(2, 4))
        self._combo.bind("<<ComboboxSelected>>", self._on_seq_change)
        tk.Label(body, text="Contacts from Mint Scout will go into this sequence.",
                 font=("Helvetica", 9), bg=BG, fg="#aaa").pack(anchor="w", pady=(0, 14))

        # Log
        self._lbl("Activity Log", body)
        self._log = tk.Text(body, height=12, font=("Courier", 9), bg="white", fg=DARK,
                             relief="solid", bd=1, state="disabled", wrap="word")
        self._log.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self._log.tag_config("green", foreground=GREEN)
        self._log.tag_config("red",   foreground="#c00")
        self._log.tag_config("gray",  foreground="#888")

    def _lbl(self, text, parent):
        tk.Label(parent, text=text, font=("Helvetica", 10, "bold"), bg=BG, fg=DARK).pack(anchor="w")

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        cfg = load_config()
        self._api_key          = cfg.get("api_key", "")
        self._selected_seq_idx = cfg.get("seq_idx", 0)

    def _connect(self):
        key = self._key_var.get().strip()
        if not key: return
        self._api_key = key
        cfg = load_config(); cfg["api_key"] = key; save_config(cfg)
        self._fetch_sequences()

    def _on_seq_change(self, _=None):
        idx = self._combo.current()
        if idx >= 0:
            self._selected_seq_idx = idx
            cfg = load_config(); cfg["seq_idx"] = idx; save_config(cfg)
            self._log_msg(f"Sequence → {self.current_seq_name()}", "green")

    # ── Sequences ─────────────────────────────────────────────────────────────

    def _fetch_sequences(self):
        self._combo.config(state="disabled")
        self._seq_var.set("Loading…")
        self._set_status("Connecting…", "orange")
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        res = apollo_post("emailer_campaigns/search", {"per_page": 25}, self._api_key)
        if res.get("error"):
            self.after(0, lambda: self._set_status("Auth failed — check API key", "#c00"))
            self.after(0, lambda: self._log_msg(res["error"], "red"))
            return
        seqs = [s for s in res.get("emailer_campaigns", []) if not s.get("archived")]
        self._sequences = seqs
        names = [("✓ " if s.get("active") else "  ") + s["name"] for s in seqs]
        def _upd():
            self._combo["values"] = names
            self._combo.config(state="readonly")
            idx = min(self._selected_seq_idx, len(seqs) - 1) if seqs else 0
            if seqs: self._combo.current(idx); self._selected_seq_idx = idx
            self._set_status(f"Ready  ·  port {PORT}", GREEN)
            self._log_msg(f"Connected — {len(seqs)} sequences loaded.", "green")
        self.after(0, _upd)

    def current_seq_name(self):
        if self._sequences and self._selected_seq_idx < len(self._sequences):
            return self._sequences[self._selected_seq_idx]["name"]
        return "None"

    def current_seq_id(self):
        if self._sequences and self._selected_seq_idx < len(self._sequences):
            return self._sequences[self._selected_seq_idx]["id"]
        return None

    # ── Process contacts (called from HTTP handler thread) ────────────────────

    def process_contacts(self, contacts):
        if not self._api_key:
            self.after(0, lambda: self._log_msg("No API key.", "red")); return
        seq_id   = self.current_seq_id()
        seq_name = self.current_seq_name()
        if not seq_id:
            self.after(0, lambda: self._log_msg("No sequence selected.", "red")); return

        total = len(contacts)
        self.after(0, lambda: self._log_msg(f"\n── {total} contact(s) from Mint Scout ──", None))
        self.after(0, lambda: self._set_status("Processing…", "orange"))

        contact_ids, found, skipped = [], 0, 0

        for i, c in enumerate(contacts, 1):
            # Build name from either split fields or 'manager' string
            mgr    = c.get("manager", "") or ""
            parts  = mgr.strip().split()
            fname  = c.get("first_name") or (parts[0] if parts else "")
            lname  = c.get("last_name")  or (" ".join(parts[1:]) if len(parts) > 1 else "")
            name   = f"{fname} {lname}".strip() or mgr or "(no name)"
            company = c.get("company") or c.get("name", "")

            self.after(0, lambda n=name, idx=i: self._log_msg(f"[{idx}/{total}] {n}", "gray"))

            match_body = {"first_name": fname, "last_name": lname, "organization_name": company}
            if c.get("email"): match_body["email"]        = c["email"]
            if c.get("phone"): match_body["phone_number"] = c["phone"]

            person = apollo_post("people/match", match_body, self._api_key).get("person")

            if not person:
                self.after(0, lambda: self._log_msg("  → not in Apollo, skipped", "gray"))
                skipped += 1
                time.sleep(0.3)
                continue

            m_name  = f"{person.get('first_name','')} {person.get('last_name','')}".strip()
            m_email = person.get("email") or "no email"
            self.after(0, lambda n=m_name, e=m_email: self._log_msg(f"  → {n} ({e})", "green"))

            org = (person.get("organization") or {})
            cbody = {
                "first_name":        person.get("first_name", fname),
                "last_name":         person.get("last_name",  lname),
                "title":             person.get("title") or "Property Manager",
                "organization_name": org.get("name") or company,
            }
            if m_email != "no email": cbody["email"] = m_email

            cid = (apollo_post("contacts", cbody, self._api_key).get("contact") or {}).get("id")
            if cid: contact_ids.append(cid); found += 1
            time.sleep(0.3)

        self.after(0, lambda f=found, s=skipped:
                   self._log_msg(f"Matched {f}  ·  Skipped {s}", None))

        if contact_ids:
            ares = apollo_post("emailer_campaigns/add_contact_ids", {
                "contact_ids": contact_ids, "emailer_campaign_id": seq_id,
            }, self._api_key)
            if ares.get("error"):
                self.after(0, lambda e=ares["error"]: self._log_msg(f"Error: {e}", "red"))
            else:
                added = len(ares.get("contacts", contact_ids))
                self.after(0, lambda a=added, s=seq_name:
                           self._log_msg(f"✓  {a} added to '{s}'", "green"))
        else:
            self.after(0, lambda: self._log_msg("No matches found.", "gray"))

        self.after(0, lambda: self._set_status(f"Ready  ·  port {PORT}", GREEN))

    # ── HTTP server ───────────────────────────────────────────────────────────

    def _start_server(self):
        try:
            server = HTTPServer(("localhost", PORT), Handler)
            self.after(0, lambda: self._log_msg(f"Listening on localhost:{PORT}", "gray"))
            server.serve_forever()
        except OSError:
            self.after(0, lambda: self._log_msg(f"Port {PORT} in use — close other bot instance.", "red"))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text, color):
        self._dot.config(fg=color)
        self._status_lbl.config(text=text)

    def _log_msg(self, text, tag=None):
        self._log.config(state="normal")
        self._log.insert(tk.END, text + "\n", tag or "")
        self._log.see(tk.END)
        self._log.config(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _app = App()
    _app.mainloop()
