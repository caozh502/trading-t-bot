"""
Railway entry point — start health server first, then bot.
"""
import os, sys, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Start health server IMMEDIATELY so Railway sees port binding
port = int(os.environ.get("PORT", 8080))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a): pass

server = HTTPServer(("0.0.0.0", port), HealthHandler)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
print(f"[railway] Health server on port {port}", flush=True)

# Now import and start the bot
sys.path.insert(0, os.path.dirname(__file__))
from bot import main
print("[railway] Starting bot...", flush=True)
main()
