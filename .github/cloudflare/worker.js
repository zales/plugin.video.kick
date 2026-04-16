/**
 * Cloudflare Worker — serves R2 bucket as a browsable Kodi repository
 * and provides a KV-backed app-token cache + proxy for Kick API.
 *
 * Bindings:
 *   BUCKET     — R2 bucket "kodi-repo"
 *   AUTH_RELAY — KV namespace (used for app_token cache)
 *
 * Secrets (wrangler secret put):
 *   KICK_CLIENT_SECRET — Kick Developer App client secret
 *
 * Rate limiting is handled at the Cloudflare edge (WAF rate-limiting rules),
 * not in the Worker itself — per-isolate in-memory counters are unreliable.
 */

const KICK_CLIENT_ID = '01KP3R6VR8RWSF3GAMAJNF0JSM';
const KICK_TOKEN_URL = 'https://id.kick.com/oauth/token';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

const PROXY_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
                 '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

function jsonResponse(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS_HEADERS, ...extra },
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let path;
    try {
      path = decodeURIComponent(url.pathname);
    } catch {
      path = url.pathname;
    }

    if (request.method === 'OPTIONS')
      return new Response(null, { status: 204, headers: CORS_HEADERS });

    // GET /app-token — returns cached client_credentials Bearer token for Kick public API
    if (path === '/app-token') {
      try {
        let appToken = await env.AUTH_RELAY.get('app_token');
        if (!appToken) {
          const resp = await fetch(KICK_TOKEN_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
              grant_type:    'client_credentials',
              client_id:     KICK_CLIENT_ID,
              client_secret: env.KICK_CLIENT_SECRET,
            }).toString(),
          });
          if (!resp.ok) {
            console.log('app-token upstream', resp.status);
            return jsonResponse({ error: 'token_upstream_error', status: resp.status }, 502);
          }
          let data;
          try { data = await resp.json(); }
          catch (e) { return jsonResponse({ error: 'token_invalid_json' }, 502); }
          appToken = data.access_token;
          if (!appToken)
            return jsonResponse({ error: 'token_fetch_failed' }, 500);
          const ttl = Math.min(Math.max(120, (data.expires_in || 3600) - 120), 86400);
          await env.AUTH_RELAY.put('app_token', appToken, { expirationTtl: ttl });
        }
        return jsonResponse({ token: appToken });
      } catch (e) {
        console.log('app-token error', e && e.message);
        return jsonResponse({ error: 'internal' }, 500);
      }
    }

    // GET /proxy/kick/* — proxy kick.com internal API with browser-like headers
    const proxyMatch = path.match(/^\/proxy\/kick(\/.+)$/);
    if (proxyMatch) {
      const kickPath = proxyMatch[1];
      // Only allow safe read-only API paths
      if (!/^\/(api\/v1|api\/v2|stream)\//.test(kickPath))
        return new Response('Forbidden', { status: 403, headers: CORS_HEADERS });
      const targetUrl = 'https://kick.com' + kickPath + (url.search || '');
      try {
        const upstreamResp = await fetch(targetUrl, {
          headers: {
            'Accept':          'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent':      PROXY_UA,
            'Referer':         'https://kick.com/',
            'Origin':          'https://kick.com',
          },
          cf: { cacheEverything: false },
        });
        const body = await upstreamResp.text();
        const upstreamCt = upstreamResp.headers.get('Content-Type') || '';
        // Kick WAF sometimes returns HTML — propagate as 502 so the client
        // can show a proper error instead of silently parsing empty JSON.
        const looksJson = upstreamCt.includes('json') ||
                          body.startsWith('{') || body.startsWith('[');
        if (!looksJson) {
          console.log('proxy non-json', upstreamResp.status, upstreamCt, targetUrl);
          return jsonResponse(
            { error: 'upstream_non_json', status: upstreamResp.status }, 502);
        }
        return new Response(body, {
          status: upstreamResp.status,
          headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
        });
      } catch (e) {
        console.log('proxy error', e && e.message, targetUrl);
        return jsonResponse({ error: 'proxy_failed' }, 502);
      }
    }

    // R2 repository browser
    const key = path.replace(/^\//, '');

    if (key && !key.endsWith('/')) {
      const rangeHeader = request.headers.get('Range');

      // Parse Range header manually — R2's { range: request } crashes on open-ended
      // ranges like "bytes=0-" which Kodi always sends during addon installs.
      let r2range;
      let isRange = false;
      if (rangeHeader) {
        const m = rangeHeader.match(/^bytes=(\d+)-(\d*)$/);
        if (m) {
          const offset = parseInt(m[1], 10);
          const end = m[2] ? parseInt(m[2], 10) : undefined;
          // "bytes=0-" with no end means full file — treat as normal GET
          if (end === undefined && offset === 0) {
            r2range = undefined;
            isRange = false;
          } else if (end !== undefined) {
            r2range = { offset, length: end - offset + 1 };
            isRange = true;
          } else {
            r2range = { offset };
            isRange = true;
          }
        }
      }

      const obj = await env.BUCKET.get(key, r2range ? { range: r2range } : undefined);
      if (!obj) return new Response('Not Found', { status: 404 });
      const headers = new Headers();
      const ext = key.split('.').pop().toLowerCase();
      const mimeTypes = { xml:'application/xml', md5:'text/plain', zip:'application/zip', png:'image/png', jpg:'image/jpeg', jpeg:'image/jpeg' };
      headers.set('Content-Type', mimeTypes[ext] || obj.httpMetadata?.contentType || 'application/octet-stream');
      headers.set('Cache-Control', (ext === 'zip' || ext === 'xml' || ext === 'md5') ? 'no-cache' : 'public, max-age=300');
      headers.set('Accept-Ranges', 'bytes');
      if (isRange && obj.range) {
        const { offset, length } = obj.range;
        headers.set('Content-Range', 'bytes ' + offset + '-' + (offset + length - 1) + '/' + obj.size);
        headers.set('Content-Length', String(length));
        return new Response(obj.body, { status: 206, headers });
      }
      headers.set('Content-Length', String(obj.size));
      return new Response(obj.body, { headers });
    }

    const listed = await env.BUCKET.list({ prefix: key, delimiter: '/' });
    const dirPath = '/' + key;
    let rows = '';
    if (key) {
      const parent = '/' + key.split('/').slice(0, -2).join('/');
      const href = escapeHtml(parent || '/');
      rows += '<tr><td><a href="' + href + '">../</a></td><td>-</td><td>-</td></tr>\n';
    }
    for (const d of (listed.delimitedPrefixes || [])) {
      const href = escapeHtml('/' + d);
      const label = escapeHtml(d.replace(key, ''));
      rows += '<tr><td><a href="' + href + '">' + label + '</a></td><td>-</td><td>-</td></tr>\n';
    }
    for (const obj of (listed.objects || [])) {
      const href = escapeHtml('/' + obj.key);
      const label = escapeHtml(obj.key.replace(key, ''));
      const mtime = obj.uploaded ? obj.uploaded.toUTCString() : '-';
      rows += '<tr><td><a href="' + href + '">' + label + '</a></td><td>' + mtime + '</td><td>' + obj.size + '</td></tr>\n';
    }

    const title = escapeHtml('Index of ' + dirPath);
    return new Response(
      '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + title + '</title></head>' +
      '<body><h1>' + title + '</h1><table><tr><th>Name</th><th>Last modified</th><th>Size</th></tr>' +
      '<tr><td colspan="3"><hr></td></tr>' + rows +
      '<tr><td colspan="3"><hr></td></tr></table></body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  },
};
