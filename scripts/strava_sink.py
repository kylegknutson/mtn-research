#!/usr/bin/env python3
"""Tiny localhost sink: the logged-in browser POSTs each Strava GPX here and we write it
to gpx/heather/. CORS-open so the strava.com page can reach it. One-time data pull."""
import http.server, socketserver, urllib.parse, pathlib, json

ROOT = pathlib.Path(__file__).resolve().parent.parent / "gpx" / "heather"
ROOT.mkdir(parents=True, exist_ok=True)
PORT = 8731

class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")  # Chrome PNA
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        self.send_response(200); self._cors(); self.end_headers()
        self.wfile.write(b"ok")
    def do_POST(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        fn = (q.get("fn", ["activity.gpx"])[0])
        fn = "".join(c for c in fn if c.isalnum() or c in "._-") or "activity.gpx"
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        (ROOT / fn).write_bytes(body)
        self.send_response(200); self._cors(); self.end_headers()
        self.wfile.write(json.dumps({"saved": fn, "bytes": len(body)}).encode())
    def log_message(self, *a): pass

with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as s:
    print(f"sink on :{PORT} -> {ROOT}", flush=True)
    s.serve_forever()
