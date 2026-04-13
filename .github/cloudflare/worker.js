/**
 * Cloudflare Worker — serves R2 bucket as a browsable Kodi repository
 * and provides a KV-backed auth relay for Kodi login via Kick OAuth 2.1 PKCE.
 *
 * Bindings:
 *   BUCKET     — R2 bucket "kodi-repo"
 *   AUTH_RELAY — KV namespace for ephemeral auth tokens (TTL 10 min)
 *
 * Secrets (wrangler secret put):
 *   KICK_CLIENT_SECRET — Kick Developer App client secret
 */

const KICK_CLIENT_ID = '01KP3R6VR8RWSF3GAMAJNF0JSM';
const KICK_AUTH_URL  = 'https://id.kick.com/oauth/authorize';
const KICK_TOKEN_URL = 'https://id.kick.com/oauth/token';
const KICK_SCOPES    = 'user:read channel:read';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

async function generatePKCE() {
  const array = new Uint8Array(64);
  crypto.getRandomValues(array);
  const verifier = btoa(String.fromCharCode(...array))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  return { verifier, challenge };
}

function connectPage(authUrl) {
  return '<!DOCTYPE html>' +
    '<html lang="cs"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Kodi KICK.com - Login</title>' +
    '<style>*{box-sizing:border-box}body{font-family:sans-serif;max-width:480px;margin:60px auto;padding:24px 20px;background:#0a120a;color:#ddd;text-align:center}' +
    'h2{color:#53fc18;font-size:1.5rem;margin-bottom:8px}.sub{color:#888;font-size:.95rem;margin-bottom:48px;line-height:1.6}' +
    '.btn{display:inline-flex;align-items:center;justify-content:center;gap:12px;padding:18px 36px;background:#53fc18;color:#0a120a;font-weight:700;font-size:1.1rem;border-radius:12px;text-decoration:none;box-shadow:0 4px 20px rgba(83,252,24,.35)}' +
    '.note{color:#555;font-size:.82rem;margin-top:40px;line-height:1.7}</style></head>' +
    '<body><h2>&#127916; KICK.com Login pro Kodi</h2>' +
    '<p class="sub">Prihlaste se do KICK. Po prihlaseni<br>se Kodi automaticky prihlas.</p>' +
    '<a class="btn" href="' + authUrl + '">' +
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="#0a120a"><path d="M2 2h4v20H2zm10 0 6 10-6 10h4l6-10L16 2z"/></svg>' +
    ' Prihlasit se pres KICK</a>' +
    '<p class="note">Vase prihlasovaci udaje nejsou sdileny s Kodi.<br>Token je ulozen lokalne na vasem zarizeni.</p>' +
    '</body></html>';
}

function errorPage(msg) {
  return new Response(
    '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Chyba</title>' +
    '<style>body{font-family:sans-serif;text-align:center;padding:60px;background:#0a120a;color:#ddd;}h2{color:#f55;}code{background:#111;padding:4px 8px;border-radius:4px;word-break:break-all;}</style></head>' +
    '<body><h2>&#10007; Chyba prihlaseni</h2><p><code>' + msg + '</code></p></body></html>',
    { status: 500, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
  );
}

export default {
  async fetch(request, env) {
    const url     = new URL(request.url);
    let path      = decodeURIComponent(url.pathname);
    const baseUrl = url.origin;

    if (request.method === 'OPTIONS')
      return new Response(null, { status: 204, headers: CORS_HEADERS });

    // GET /connect/:id
    const connectMatch = path.match(/^\/connect\/([a-zA-Z0-9_-]{8,64})$/);
    if (connectMatch) {
      const sessionId = connectMatch[1];
      const { verifier, challenge } = await generatePKCE();
      await env.AUTH_RELAY.put('pkce:' + sessionId, verifier, { expirationTtl: 600 });
      const params = new URLSearchParams({
        response_type:         'code',
        client_id:             KICK_CLIENT_ID,
        redirect_uri:          baseUrl + '/oauth/callback',
        scope:                 KICK_SCOPES,
        code_challenge:        challenge,
        code_challenge_method: 'S256',
        state:                 sessionId,
      });
      return new Response(connectPage(KICK_AUTH_URL + '?' + params), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    // GET /oauth/callback
    if (path === '/oauth/callback') {
      const code  = url.searchParams.get('code');
      const state = url.searchParams.get('state');
      const error = url.searchParams.get('error');
      if (error || !code || !state)
        return errorPage('Login zrusen: ' + (error || 'chybi parametry'));
      if (!/^[a-zA-Z0-9_-]{8,64}$/.test(state))
        return errorPage('Neplatny state parametr');
      try {
        const verifier = await env.AUTH_RELAY.get('pkce:' + state);
        if (!verifier) return errorPage('PKCE session vyprsela nebo nenalezena');

        const tokenResp = await fetch(KICK_TOKEN_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            grant_type:    'authorization_code',
            client_id:     KICK_CLIENT_ID,
            client_secret: env.KICK_CLIENT_SECRET,
            redirect_uri:  baseUrl + '/oauth/callback',
            code_verifier: verifier,
            code,
          }).toString(),
        });
        const tokenData = await tokenResp.json();
        const bearer = tokenData.access_token;
        if (!bearer)
          return errorPage('Token error (' + tokenResp.status + '): ' + JSON.stringify(tokenData));

        await env.AUTH_RELAY.put('token:' + state, bearer, { expirationTtl: 600 });
        await env.AUTH_RELAY.delete('pkce:' + state);

        return new Response(
          '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Hotovo!</title>' +
          '<style>body{font-family:sans-serif;text-align:center;padding:60px;background:#0a120a;color:#ddd;}' +
          'h2{color:#53fc18;font-size:2rem;}p{color:#aaa;margin-top:16px;}</style></head>' +
          '<body><h2>&#10003; Prihlaseni uspesne!</h2><p>Vrate se do Kodi - jste prihlaseni.</p></body></html>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      } catch (e) {
        return errorPage('Neocekavana chyba: ' + e.message);
      }
    }

    // GET /token/:id
    const tokenMatch = path.match(/^\/token\/([a-zA-Z0-9_-]{8,64})$/);
    if (tokenMatch && request.method === 'GET') {
      const token = await env.AUTH_RELAY.get('token:' + tokenMatch[1]);
      if (!token) return new Response('', { status: 204, headers: CORS_HEADERS });
      await env.AUTH_RELAY.delete('token:' + tokenMatch[1]);
      return new Response(JSON.stringify({ token }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      });
    }

    // R2 repository browser
    const key = path.replace(/^\//, '');

    if (key && !key.endsWith('/')) {
      const rangeHeader = request.headers.get('Range');
      const obj = await env.BUCKET.get(key, rangeHeader ? { range: request.headers } : undefined);
      if (!obj) return new Response('Not Found', { status: 404 });
      const headers = new Headers();
      const ext = key.split('.').pop().toLowerCase();
      const mimeTypes = { xml:'application/xml', md5:'text/plain', zip:'application/zip', png:'image/png', jpg:'image/jpeg', jpeg:'image/jpeg' };
      headers.set('Content-Type', mimeTypes[ext] || obj.httpMetadata?.contentType || 'application/octet-stream');
      headers.set('Cache-Control', ext === 'zip' ? 'no-cache' : 'public, max-age=300');
      headers.set('Accept-Ranges', 'bytes');
      if (obj.range) {
        const { offset, length } = obj.range;
        headers.set('Content-Range', 'bytes ' + offset + '-' + (offset + length - 1) + '/' + obj.size);
        return new Response(obj.body, { status: 206, headers });
      }
      return new Response(obj.body, { headers });
    }

    const listed = await env.BUCKET.list({ prefix: key, delimiter: '/' });
    const dirPath = '/' + key;
    let rows = '';
    if (key) {
      const parent = '/' + key.split('/').slice(0, -2).join('/');
      rows += '<tr><td><a href="' + (parent || '/') + '">../</a></td><td>-</td><td>-</td></tr>\n';
    }
    for (const d of (listed.delimitedPrefixes || []))
      rows += '<tr><td><a href="/' + d + '">' + d.replace(key, '') + '</a></td><td>-</td><td>-</td></tr>\n';
    for (const obj of (listed.objects || []))
      rows += '<tr><td><a href="/' + obj.key + '">' + obj.key.replace(key, '') + '</a></td><td>' + (obj.uploaded ? obj.uploaded.toUTCString() : '-') + '</td><td>' + obj.size + '</td></tr>\n';

    return new Response(
      '<!DOCTYPE HTML><html><head><title>Index of ' + dirPath + '</title></head><body><h1>Index of ' + dirPath + '</h1><table><tr><th>Name</th><th>Last modified</th><th>Size</th></tr><tr><td colspan="3"><hr></td></tr>' + rows + '<tr><td colspan="3"><hr></td></tr></table></body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  },
};
