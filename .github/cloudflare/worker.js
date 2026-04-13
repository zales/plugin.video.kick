/**
 * Cloudflare Worker — serves R2 bucket as a browsable Kodi repository
 * and provides a KV-backed auth relay for Kodi Google login.
 *
 * Bindings:
 *   BUCKET     — R2 bucket "kodi-repo"
 *   AUTH_RELAY — KV namespace for ephemeral auth tokens (TTL 10 min)
 */

// ---------------------------------------------------------------------------
// Auth relay helpers
// ---------------------------------------------------------------------------

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function connectPage(sessionId, baseUrl) {
  const bookmarklet = `javascript:(function(){var d={};var ls={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);ls[k]=localStorage.getItem(k);}d.localStorage=ls;d.token=localStorage.getItem('token')||localStorage.getItem('accessToken')||'';fetch('${baseUrl}/token/${sessionId}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(function(r){return r.text();}).then(function(t){alert('Kodi: '+t+' — vra\\u0165te se do Kodi!');}).catch(function(e){alert('Chyba: '+e.message);});})();`;

  const script = `javascript:(function(){var d={};var ls={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);ls[k]=localStorage.getItem(k);}d.localStorage=ls;d.token=localStorage.getItem('token')||localStorage.getItem('accessToken')||'';fetch('${baseUrl}/token/${sessionId}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(function(r){return r.text();}).then(function(t){alert('Kodi: '+t);}).catch(function(e){alert('Chyba: '+e.message);});})();`;

  return `<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kodi KICK.com — Login</title>
<style>
  *    { box-sizing: border-box; }
  body { font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 24px 16px;
         background: #0a120a; color: #ddd; }
  h2   { color: #53fc18; margin-bottom: 24px; font-size: 1.3rem; }
  .step{ display: flex; align-items: flex-start; gap: 14px; margin-bottom: 22px; }
  .num { flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
         background: #53fc18; color: #000; font-weight: 800; font-size: 1.1rem;
         display: flex; align-items: center; justify-content: center; }
  .txt { line-height: 1.5; padding-top: 6px; }
  .btn { display: block; width: 100%; padding: 16px; margin-top: 10px;
         background: #53fc18; color: #000; font-weight: 800; font-size: 1.1rem;
         border: none; border-radius: 10px; cursor: pointer; text-align: center; }
  .ok  { display: none; color: #53fc18; font-size: .9rem; margin-top: 6px; text-align: center; }
  .hint{ color: #888; font-size: .82rem; margin-top: 6px; }
  .hint b { color: #ddd; }
</style>
</head>
<body>
<h2>&#127916; KICK.com Login pro Kodi</h2>

<div class="step">
  <div class="num">1</div>
  <div class="txt">
    <strong>Zkopírujte skript</strong>
    <button class="btn" onclick="copyScript()">&#128203; Kopírovat skript</button>
    <div class="ok" id="m1">&#10003; Zkopírováno!</div>
    <div class="hint">Skript vložíte do adresního řádku prohlížeče na kroku 3.</div>
  </div>
</div>

<div class="step">
  <div class="num">2</div>
  <div class="txt">
    <strong>Otevřete kick.com/login <em>v prohlížeči</em></strong>
    <button class="btn" style="background:#1a2a1a;color:#53fc18;border:2px solid #53fc18"
            onclick="copyKickUrl()">&#128203; Kopírovat kick.com/login</button>
    <div class="ok" id="m2">&#10003; Zkopírováno!</div>
    <div class="hint"><b>Otevřete Chrome nebo Safari</b>, vložte adresu a přihlaste se přes Google.<br>
    <span>(Netapujte odkaz — mohla by se otevřít aplikace.)</span></div>
  </div>
</div>

<div class="step">
  <div class="num">3</div>
  <div class="txt">
    <strong>Vložte skript do adresního řádku</strong>
    <div class="hint" style="color:#ddd;font-size:.95rem">
      Po přihlášení ťukněte na adresní řádek (kde je <em>kick.com</em>),
      <b>vložte</b> zkopírovaný skript a potvrďte Enter / Go.
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
var SCRIPT = ${JSON.stringify(script)};
function copyScript() {
  copyText(SCRIPT, 'm1');
}
function copyKickUrl() {
  copyText('https://kick.com/login', 'm2');
}
function copyText(text, msgId) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      document.getElementById(msgId).style.display = 'block';
    });
  } else {
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    document.getElementById(msgId).style.display = 'block';
  }
}
</script>
</body>
</html>`;
}

function extractToken(data) {
  const KEYS = ['token', 'access_token', 'accessToken', 'bearer', 'auth_token', 'auth._token.local'];
  for (const k of KEYS) {
    const v = data[k];
    if (v && typeof v === 'string' && v.length > 20) return v.trim();
  }
  const ls = data.localStorage;
  if (ls && typeof ls === 'object') {
    for (const [k, v] of Object.entries(ls)) {
      if (typeof v !== 'string') continue;
      if (v.length > 40 && v.length < 2000 && !v.includes(' ')) {
        if (['token','auth','bearer'].some(h => k.toLowerCase().includes(h))) return v.trim();
      }
    }
    for (const [, v] of Object.entries(ls)) {
      if (typeof v === 'string' && v.length > 40 && v.length < 2000 && !v.includes(' ')) return v.trim();
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Main fetch handler
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env) {
    const url  = new URL(request.url);
    let path   = decodeURIComponent(url.pathname);
    const baseUrl = url.origin;

    // -----------------------------------------------------------------------
    // Auth relay routes
    // -----------------------------------------------------------------------

    // OPTIONS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // GET /connect/:id  — show mobile instructions page
    const connectMatch = path.match(/^\/connect\/([a-zA-Z0-9_-]{8,64})$/);
    if (connectMatch) {
      const sessionId = connectMatch[1];
      return new Response(connectPage(sessionId, baseUrl), {
        headers: { 'Content-Type': 'text/html; charset=utf-8', ...CORS_HEADERS },
      });
    }

    // POST /token/:id  — bookmarklet posts token here
    const tokenMatch = path.match(/^\/token\/([a-zA-Z0-9_-]{8,64})$/);
    if (tokenMatch && request.method === 'POST') {
      const sessionId = tokenMatch[1];
      let data;
      try { data = await request.json(); } catch { return new Response('Bad JSON', { status: 400, headers: CORS_HEADERS }); }
      const token = extractToken(data);
      if (!token) return new Response('Token not found in payload', { status: 400, headers: CORS_HEADERS });
      // Store in KV with 10 minute TTL
      await env.AUTH_RELAY.put(`token:${sessionId}`, token, { expirationTtl: 600 });
      return new Response('OK', { status: 200, headers: CORS_HEADERS });
    }

    // GET /token/:id  — Kodi polls for token
    if (tokenMatch && request.method === 'GET') {
      const sessionId = tokenMatch[1];
      const token = await env.AUTH_RELAY.get(`token:${sessionId}`);
      if (!token) return new Response('', { status: 204, headers: CORS_HEADERS });
      // Delete after Kodi reads it
      await env.AUTH_RELAY.delete(`token:${sessionId}`);
      return new Response(JSON.stringify({ token }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      });
    }

    // -----------------------------------------------------------------------
    // R2 repository routes (existing)
    // -----------------------------------------------------------------------

    const key = path.replace(/^\//, '');

    // --- Serve file directly ---
    if (key && !key.endsWith('/')) {
      const rangeHeader = request.headers.get('Range');
      const obj = await env.BUCKET.get(key, rangeHeader ? { range: request.headers } : undefined);
      if (!obj) return new Response('Not Found', { status: 404 });
      const headers = new Headers();
      const ext = key.split('.').pop().toLowerCase();
      const mimeTypes = {
        xml: 'application/xml',
        md5: 'text/plain',
        zip: 'application/zip',
        png: 'image/png',
        jpg: 'image/jpeg',
        jpeg: 'image/jpeg',
      };
      headers.set('Content-Type', mimeTypes[ext] || obj.httpMetadata?.contentType || 'application/octet-stream');
      headers.set('Cache-Control', ext === 'zip' ? 'no-cache' : 'public, max-age=300');
      headers.set('Accept-Ranges', 'bytes');
      if (obj.range) {
        const { offset, length } = obj.range;
        headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${obj.size}`);
        return new Response(obj.body, { status: 206, headers });
      }
      return new Response(obj.body, { headers });
    }

    // --- Serve index.html for root ---
    if (!key) {
      const obj = await env.BUCKET.get('index.html');
      if (obj) {
        const headers = new Headers();
        headers.set('Content-Type', 'text/html; charset=utf-8');
        headers.set('Cache-Control', 'public, max-age=300');
        return new Response(obj.body, { headers });
      }
    }

    // --- Directory listing ---
    const prefix  = key;  // '' for root, 'subdir/' for subdirs
    const listed  = await env.BUCKET.list({ prefix, delimiter: '/' });

    // Build Apache-style HTML (Kodi parses this format)
    const dirPath = '/' + prefix;
    let rows = '';

    // Parent directory link (not for root)
    if (prefix) {
      const parent = '/' + prefix.split('/').slice(0, -2).join('/');
      rows += `<tr><td><a href="${parent || '/'}">../</a></td><td>-</td><td>-</td></tr>\n`;
    }

    // Sub-directories
    for (const d of (listed.delimitedPrefixes || [])) {
      const name = d.replace(prefix, '');
      rows += `<tr><td><a href="/${d}">${name}</a></td><td>-</td><td>-</td></tr>\n`;
    }

    // Files
    for (const obj of (listed.objects || [])) {
      const name    = obj.key.replace(prefix, '');
      const size    = obj.size;
      const modified = obj.uploaded?.toUTCString() ?? '-';
      rows += `<tr><td><a href="/${obj.key}">${name}</a></td><td>${modified}</td><td>${size}</td></tr>\n`;
    }

    const html = `<!DOCTYPE HTML>
<html><head><title>Index of ${dirPath}</title></head>
<body><h1>Index of ${dirPath}</h1>
<table>
<tr><th>Name</th><th>Last modified</th><th>Size</th></tr>
<tr><td colspan="3"><hr></td></tr>
${rows}
<tr><td colspan="3"><hr></td></tr>
</table></body></html>`;

    return new Response(html, {
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  },
};
