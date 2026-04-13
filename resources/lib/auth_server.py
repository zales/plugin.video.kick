# -*- coding: UTF-8 -*-
"""
Local HTTP server for OAuth / Google login flow.

Flow:
  1. Addon starts this server on localhost:PORT
  2. User opens http://localhost:PORT in their browser (or Kodi opens it)
  3. Page shows a bookmarklet the user drags to bookmarks bar
  4. User goes to kick.com, logs in with Google
  5. User clicks the bookmarklet — it extracts the Bearer token and POSTs to localhost
  6. Addon picks up the token and stores it
"""
import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

_token_received = None
_server = None
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(port=27015):
    """Start server in a daemon thread. Returns the port number."""
    global _server
    reset()
    _server = HTTPServer(('0.0.0.0', port), _Handler)
    t = threading.Thread(target=_server.serve_forever, daemon=True)
    t.start()
    return port


def get_local_ip():
    """Best-effort: return LAN IP of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def stop():
    global _server
    if _server:
        _server.shutdown()
        _server = None


def get_token():
    """Return received token or None."""
    return _token_received


def reset():
    global _token_received
    _token_received = None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass  # silence access log

    # ------------------------------------------------------------------
    # GET /          → instructions page with bookmarklet
    # GET /token?t=  → receive token via URL redirect from bookmarklet
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/token':
            params = parse_qs(parsed.query)
            token = params.get('t', [None])[0]
            self._save_token(token)
            if token:
                self._respond(200, 'text/html', _SUCCESS_PAGE)
            else:
                self._respond(400, 'text/plain', 'No token in request')
            return

        # Default: instructions page
        port = self.server.server_address[1]
        lan_ip = get_local_ip()
        self._respond(200, 'text/html', _instructions_page(port, lan_ip))

    # ------------------------------------------------------------------
    # POST /token  → receive token as JSON body (fetch() from bookmarklet)
    # ------------------------------------------------------------------
    def do_POST(self):
        if urlparse(self.path).path != '/token':
            self._respond(404, 'text/plain', 'Not found')
            return

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._respond(400, 'text/plain', 'Invalid JSON')
            return

        token = _extract_token(data)
        self._save_token(token)
        if token:
            self._respond(200, 'text/plain', 'OK')
        else:
            self._respond(400, 'text/plain', 'Token not found in payload')

    def do_OPTIONS(self):
        self._respond(200, 'text/plain', '')

    # ------------------------------------------------------------------
    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.wfile.write(body)

    def _save_token(self, token):
        global _token_received
        if token:
            with _lock:
                _token_received = token


# ---------------------------------------------------------------------------
# Token extraction from bookmarklet payload
# ---------------------------------------------------------------------------

def _extract_token(data):
    """Try to find a Bearer token in the payload sent by the bookmarklet."""
    # Direct field names commonly used by kick.com / Sanctum / Nuxt Auth
    for key in ('token', 'access_token', 'accessToken', 'bearer', 'auth_token',
                'auth._token.local'):
        val = data.get(key)
        if val and isinstance(val, str) and len(val) > 20:
            return val.strip()

    # Scan localStorage dump
    ls = data.get('localStorage')
    if isinstance(ls, dict):
        for key, val in ls.items():
            if not isinstance(val, str):
                continue
            # Bearer tokens / JWTs are typically 100–2000 chars, no spaces
            if 40 < len(val) < 2000 and ' ' not in val:
                # Prefer keys with "token" or "auth" in their name
                if any(hint in key.lower() for hint in ('token', 'auth', 'bearer')):
                    return val.strip()
        # Second pass: any plausible string even without keyword in key
        for key, val in ls.items():
            if isinstance(val, str) and 40 < len(val) < 2000 and ' ' not in val:
                return val.strip()

    return None


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

def _instructions_page(port, lan_ip='127.0.0.1'):
    local_url = 'http://{}:{}'.format(lan_ip, port)
    bookmarklet = (
        "javascript:(function(){{"
        "var d={{}};"
        "var ls={{}};"
        "for(var i=0;i<localStorage.length;i++){{"
        "var k=localStorage.key(i);ls[k]=localStorage.getItem(k);"
        "}}"
        "d.localStorage=ls;"
        "d.token=localStorage.getItem('token')||localStorage.getItem('accessToken')||'';"
        "fetch('http://localhost:{port}/token',{{"
        "method:'POST',"
        "headers:{{'Content-Type':'application/json'}},"
        "body:JSON.stringify(d)"
        "}}).then(function(r){{return r.text();}}).then(function(t){{"
        "alert('Kodi: '+t+' — return to Kodi!');"
        "}}).catch(function(e){{"
        "alert('Error: '+e.message);"
        "}});"
        "}})();"
    ).format(port=port)

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kodi KICK.com — Google Login</title>
<style>
  body {{ font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px;
          background: #0a120a; color: #ddd; }}
  h2   {{ color: #53fc18; }}
  ol   {{ line-height: 2.6; }}
  a.bm {{ display: inline-block; padding: 10px 22px; background: #53fc18; color: #000;
          font-weight: bold; border-radius: 6px; text-decoration: none; font-size: 1rem; }}
  a    {{ color: #53fc18; }}
  code {{ background: #111; padding: 2px 8px; border-radius: 3px; }}
</style>
</head>
<body>
<h2>KICK.com — Google Login for Kodi</h2>
<p>Open this page on any device in your network:<br>
<a href="{local_url}" style="color:#53fc18">{local_url}</a></p>
<ol>
  <li>Drag this button to your <b>bookmarks bar</b>:&nbsp;
      <a class="bm" href="{bookmarklet}">Get Kick Token</a></li>
  <li>Open <a href="https://kick.com/login" target="_blank">kick.com/login</a>
      and log in with <b>Google</b></li>
  <li>After logging in, click the <b>Get Kick Token</b> bookmark while on kick.com</li>
  <li>A popup will say <em>"Kodi: OK"</em> — return to Kodi, you are logged in!</li>
</ol>
<p style="color:#888;font-size:.85rem">
  This page is served locally by Kodi on <code>{local_url}</code>.
  No data leaves your machine.
</p>
</body>
</html>""".format(bookmarklet=bookmarklet, port=port, local_url=local_url)


_SUCCESS_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Logged in!</title>
<style>body{{font-family:sans-serif;text-align:center;margin-top:80px;background:#0a120a;color:#ddd;}}
h2{{color:#53fc18;}}</style></head>
<body><h2>&#10003; Logged in!</h2><p>Return to Kodi — you are now logged in.</p></body></html>"""
