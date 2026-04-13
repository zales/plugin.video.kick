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


def get_qr_image(url):
    """Download a QR code PNG for *url* from a free API.

    Returns the path to a temporary file.  Caller is responsible for deleting it.
    Raises on network error so the caller can fall back gracefully.
    """
    import tempfile
    import urllib.request
    import urllib.parse
    api = (
        'https://api.qrserver.com/v1/create-qr-code/'
        '?size=400x400&margin=2&data={}'
    ).format(urllib.parse.quote(url, safe=''))
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    urllib.request.urlretrieve(api, tmp.name)
    return tmp.name


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
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kodi KICK.com — Login</title>
<style>
  *    {{ box-sizing: border-box; }}
  body {{ font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 24px 16px;
          background: #0a120a; color: #ddd; }}
  h2   {{ color: #53fc18; margin-bottom: 24px; font-size: 1.3rem; }}
  .step{{ display: flex; align-items: flex-start; gap: 14px; margin-bottom: 22px; }}
  .num {{ flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
          background: #53fc18; color: #000; font-weight: 800; font-size: 1.1rem;
          display: flex; align-items: center; justify-content: center; }}
  .txt {{ line-height: 1.5; padding-top: 6px; }}
  .btn {{ display: block; width: 100%; padding: 16px; margin-top: 10px;
          background: #53fc18; color: #000; font-weight: 800; font-size: 1.1rem;
          border: none; border-radius: 10px; cursor: pointer; text-align: center;
          text-decoration: none; }}
  .btn.secondary {{ background: #1a2a1a; color: #53fc18; border: 2px solid #53fc18; }}
  #copy-msg {{ display: none; color: #53fc18; font-size: .9rem; margin-top: 6px;
               text-align: center; }}
  .hint {{ color: #888; font-size: .82rem; margin-top: 6px; }}
</style>
</head>
<body>
<h2>&#127916; KICK.com Login pro Kodi</h2>

<div class="step">
  <div class="num">1</div>
  <div class="txt">
    <strong>Zkopírujte skript</strong>
    <button class="btn" onclick="copyScript()">&#128203; Kopírovat skript</button>
    <div id="copy-msg">&#10003; Zkopírováno!</div>
    <div class="hint">Skript bude vložen do adresního řádku prohlížeče.</div>
  </div>
</div>

<div class="step">
  <div class="num">2</div>
  <div class="txt">
    <strong>Otevřete kick.com/login <em>v prohlížeči</em></strong>
    <button class="btn secondary" onclick="copyKickUrl()">&#128203; Kopírovat kick.com/login</button>
    <div id="kick-msg" style="display:none;color:#53fc18;font-size:.9rem;margin-top:6px;text-align:center">&#10003; Zkopírováno!</div>
    <div class="hint" style="color:#ddd">
      Otevřete <strong>Chrome</strong> nebo <strong>Safari</strong>, vložte adresu do řádku a přihlaste se přes Google.<br>
      <span style="color:#888">(Netapujte odkaz — otevřelo by to aplikaci.)</span>
    </div>
  </div>
</div>

<div class="step">
  <div class="num">3</div>
  <div class="txt">
    <strong>Vložte skript do adresního řádku</strong>
    <div class="hint" style="color:#ddd;font-size:.95rem">
      Ťukněte na adresní řádek prohlížeče (kde je <em>kick.com</em>),
      <b>vložte</b> zkopírovaný text a potvrďte klávesou Enter / Go.
    </div>
  </div>
</div>

<div class="step">
  <div class="num">4</div>
  <div class="txt">
    <strong>Hotovo!</strong>
    <div class="hint" style="color:#ddd;font-size:.95rem">
      Zobrazí se hláška „Kodi: OK" — vraťte se do Kodi, jste přihlášeni.
    </div>
  </div>
</div>

<script>
var SCRIPT = {bookmarklet_json};
function copyScript() {{
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(SCRIPT).then(function() {{
      document.getElementById('copy-msg').style.display = 'block';
    }});
  }} else {{
    var ta = document.createElement('textarea');
    ta.value = SCRIPT;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    document.getElementById('copy-msg').style.display = 'block';
  }}
}}
function copyKickUrl() {{
  var url = 'https://kick.com/login';
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(url).then(function() {{
      document.getElementById('kick-msg').style.display = 'block';
    }});
  }} else {{
    var ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    document.getElementById('kick-msg').style.display = 'block';
  }}
}}
</script>
</body>
</html>""".format(bookmarklet_json=json.dumps(bookmarklet), port=port, local_url=local_url)


_SUCCESS_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Logged in!</title>
<style>body{{font-family:sans-serif;text-align:center;margin-top:80px;background:#0a120a;color:#ddd;}}
h2{{color:#53fc18;}}</style></head>
<body><h2>&#10003; Logged in!</h2><p>Return to Kodi — you are now logged in.</p></body></html>"""
