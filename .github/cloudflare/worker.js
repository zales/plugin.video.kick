/**
 * Cloudflare Worker — serves R2 bucket as a browsable Kodi repository
 * and provides a KV-backed auth relay for Kodi Google login.
 *
 * Bindings:
 *   BUCKET     — R2 bucket "kodi-repo"
 *   AUTH_RELAY — KV namespace for ephemeral auth tokens (TTL 10 min)
 *
 * No secrets needed — uses Firebase createAuthUri which uses Kick's own registered OAuth client.
 */

const FIREBASE_API_KEY = 'AIzaSyBt03MQfMaVa2QNnADsIUgT1LBOOx7SET0';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

async function getConnectPage(sessionId, baseUrl, env) {
  const continueUri = `${baseUrl}/oauth/callback?uuid=${sessionId}`;
  const caResp = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:createAuthUri?key=${FIREBASE_API_KEY}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ providerId: 'google.com', continueUri }) }
  );
  const caData = await caResp.json();
  if (!caData.authUri) throw new Error('createAuthUri failed: ' + JSON.stringify(caData));
  await env.AUTH_RELAY.put(`fbsession:${sessionId}`, caData.sessionId, { expirationTtl: 600 });
  const googleUrl = caData.authUri;
  return `<!DOCTYPE html>
<html lang="cs"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kodi KICK.com - Login</title>
<style>
*{box-sizing:border-box}
body{font-family:sans-serif;max-width:480px;margin:60px auto;padding:24px 20px;background:#0a120a;color:#ddd;text-align:center}
h2{color:#53fc18;font-size:1.5rem;margin-bottom:8px}
.sub{color:#888;font-size:.95rem;margin-bottom:48px;line-height:1.6}
.btn{display:inline-flex;align-items:center;gap:14px;padding:18px 36px;background:#fff;color:#111;font-weight:700;font-size:1.1rem;border-radius:12px;text-decoration:none;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.btn svg{width:26px;height:26px;flex-shrink:0}
.note{color:#555;font-size:.82rem;margin-top:40px;line-height:1.7}
</style></head>
<body>
<h2>&#127916; KICK.com Login pro Kodi</h2>
<p class="sub">Prihlaste se pres Google. Po prihlaseni<br>se Kodi automaticky prihlas.</p>
<a class="btn" href="${googleUrl}">
  <svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
  Prihlasit se pres Google
</a>
<p class="note">Vase prihlasovaci udaje nejsou sdileny s Kodi.<br>Token je ulozen lokalne na vasem zarizeni.</p>
</body></html>`;
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
      try {
        const html = await getConnectPage(connectMatch[1], baseUrl, env);
        return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      } catch (e) {
        return errorPage('Connect page error: ' + e.message);
      }
    }

    // GET /oauth/callback — serves JS fragment-reader page
    if (path === '/oauth/callback') {
      const uuid  = url.searchParams.get('uuid');
      const error = url.searchParams.get('error');
      if (error) return errorPage('Google login zrusen: ' + error);
      if (!uuid || !/^[a-zA-Z0-9_-]{8,64}$/.test(uuid))
        return errorPage('Chybi nebo neplatny UUID parametr');
      const safeUuid = uuid.replace(/[^a-zA-Z0-9_-]/g, '');
      return new Response(
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Prihlasovani...</title>' +
        '<style>body{font-family:sans-serif;text-align:center;padding:60px;background:#0a120a;color:#ddd;}' +
        'h2{color:#53fc18;font-size:1.6rem;}p{color:#aaa;margin-top:16px;}</style></head>' +
        '<body><h2>&#9203; Prihlasovani...</h2><p id="msg">Prosim cekejte.</p>' +
        '<script>(function(){' +
          'var hash=window.location.hash.substring(1);' +
          'var p=new URLSearchParams(hash);' +
          'var idToken=p.get("id_token");' +
          'if(!idToken){document.getElementById("msg").textContent="Chyba: id_token nenalezen v URL: "+window.location.hash;return;}' +
          'fetch("/oauth/finalize",{method:"POST",headers:{"Content-Type":"application/json"},' +
          'body:JSON.stringify({uuid:"' + safeUuid + '",requestUri:window.location.href})})' +
          '.then(function(r){return r.json();})' +
          '.then(function(d){' +
            'if(d.ok){document.querySelector("h2").textContent="\u2713 Prihlaseni uspesne!";' +
            'document.getElementById("msg").textContent="Vrate se do Kodi - jste prihlaseni.";}' +
            'else{document.querySelector("h2").style.color="#f55";document.querySelector("h2").textContent="\u2717 Chyba";' +
            'document.getElementById("msg").textContent=d.error||("status "+d.status);}' +
          '}).catch(function(e){document.getElementById("msg").textContent="Fetch error: "+e.message;});' +
        '})();</script></body></html>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    }

    // POST /oauth/finalize — exchanges Firebase session+idToken for Kick bearer
    if (path === '/oauth/finalize' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { uuid, requestUri } = body;
        if (!uuid || !requestUri || !/^[a-zA-Z0-9_-]{8,64}$/.test(uuid))
          return new Response(JSON.stringify({ ok: false, error: 'Missing/invalid params' }), { status: 400, headers: { 'Content-Type': 'application/json' } });

        const fbSessionId = await env.AUTH_RELAY.get(`fbsession:${uuid}`);
        if (!fbSessionId)
          return new Response(JSON.stringify({ ok: false, error: 'Session expired or not found' }), { status: 400, headers: { 'Content-Type': 'application/json' } });

        const fbResp = await fetch(
          `https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=${FIREBASE_API_KEY}`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sessionId: fbSessionId, requestUri, returnIdpCredential: true, returnSecureToken: true }) }
        );
        const fbData = await fbResp.json();
        if (!fbData.idToken)
          return new Response(JSON.stringify({ ok: false, error: 'Firebase: ' + JSON.stringify(fbData) }), { headers: { 'Content-Type': 'application/json' } });

        const kickResp = await fetch('https://kick.com/api/v1/google-mobile-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ token: fbData.idToken }),
        });
        const kickData = await kickResp.json();
        const bearer = kickData.token || kickData.access_token
          || (kickData.data && (kickData.data.token || kickData.data.access_token));
        if (!bearer)
          return new Response(JSON.stringify({ ok: false, error: `Kick (${kickResp.status}): ${JSON.stringify(kickData)}` }), { headers: { 'Content-Type': 'application/json' } });

        await env.AUTH_RELAY.put(`token:${uuid}`, bearer, { expirationTtl: 600 });
        await env.AUTH_RELAY.delete(`fbsession:${uuid}`);
        return new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: e.message }), { headers: { 'Content-Type': 'application/json' } });
      }
    }

    // GET /token/:id
    const tokenMatch = path.match(/^\/token\/([a-zA-Z0-9_-]{8,64})$/);
    if (tokenMatch && request.method === 'GET') {
      const token = await env.AUTH_RELAY.get(`token:${tokenMatch[1]}`);
      if (!token) return new Response('', { status: 204, headers: CORS_HEADERS });
      await env.AUTH_RELAY.delete(`token:${tokenMatch[1]}`);
      return new Response(JSON.stringify({ token }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      });
    }

    // R2 repository
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
        headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${obj.size}`);
        return new Response(obj.body, { status: 206, headers });
      }
      return new Response(obj.body, { headers });
    }

    const listed = await env.BUCKET.list({ prefix: key, delimiter: '/' });
    const dirPath = '/' + key;
    let rows = '';
    if (key) {
      const parent = '/' + key.split('/').slice(0, -2).join('/');
      rows += `<tr><td><a href="${parent || '/'}">../</a></td><td>-</td><td>-</td></tr>\n`;
    }
    for (const d of (listed.delimitedPrefixes || []))
      rows += `<tr><td><a href="/${d}">${d.replace(key, '')}</a></td><td>-</td><td>-</td></tr>\n`;
    for (const obj of (listed.objects || []))
      rows += `<tr><td><a href="/${obj.key}">${obj.key.replace(key, '')}</a></td><td>${obj.uploaded ? obj.uploaded.toUTCString() : '-'}</td><td>${obj.size}</td></tr>\n`;

    return new Response(
      `<!DOCTYPE HTML><html><head><title>Index of ${dirPath}</title></head><body><h1>Index of ${dirPath}</h1><table><tr><th>Name</th><th>Last modified</th><th>Size</th></tr><tr><td colspan="3"><hr></td></tr>${rows}<tr><td colspan="3"><hr></td></tr></table></body></html>`,
      { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  },
};
