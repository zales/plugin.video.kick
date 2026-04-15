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
 */

const KICK_CLIENT_ID = '01KP3R6VR8RWSF3GAMAJNF0JSM';
const KICK_TOKEN_URL = 'https://id.kick.com/oauth/token';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// ---------------------------------------------------------------------------
// Simple in-memory sliding-window rate limiter (per-IP, per isolate).
// Not shared across Workers isolates, but sufficient to block obvious abuse.
// ---------------------------------------------------------------------------
const RATE_WINDOW_MS = 60_000;   // 1 minute
const RATE_MAX_HITS  = 60;       // max requests per window
const _hits = new Map();         // ip -> [timestamp, ...]

function _rateOk(ip) {
  const now = Date.now();
  let timestamps = _hits.get(ip);
  if (!timestamps) {
    timestamps = [];
    _hits.set(ip, timestamps);
  }
  // Evict entries older than the window
  while (timestamps.length && timestamps[0] <= now - RATE_WINDOW_MS)
    timestamps.shift();
  if (timestamps.length >= RATE_MAX_HITS) return false;
  timestamps.push(now);
  // Prevent memory leak: drop IPs with no recent hits (lazy GC)
  if (_hits.size > 10_000) {
    for (const [k, v] of _hits) {
      if (!v.length) _hits.delete(k);
      if (_hits.size <= 5_000) break;
    }
  }
  return true;
}

export default {
  async fetch(request, env) {
    const url     = new URL(request.url);
    let path      = decodeURIComponent(url.pathname);

    if (request.method === 'OPTIONS')
      return new Response(null, { status: 204, headers: CORS_HEADERS });

    // Rate-limit proxied / token endpoints (R2 serving is unlimited)
    const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';
    if ((path === '/app-token' || path.startsWith('/proxy/')) && !_rateOk(clientIp))
      return new Response(JSON.stringify({ error: 'rate_limited' }), {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '60', ...CORS_HEADERS },
      });

    // GET /app-token — returns cached client_credentials Bearer token for Kick public API
    if (path === '/app-token') {
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
        const data = await resp.json();
        appToken = data.access_token;
        if (!appToken)
          return new Response(JSON.stringify({ error: 'token_fetch_failed' }), {
            status: 500, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
          });
        const ttl = Math.min(Math.max(120, (data.expires_in || 3600) - 120), 86400);
        await env.AUTH_RELAY.put('app_token', appToken, { expirationTtl: ttl });
      }
      return new Response(JSON.stringify({ token: appToken }), {
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      });
    }

    // GET /proxy/kick/* — proxy kick.com internal API with browser-like headers
    const proxyMatch = path.match(/^\/proxy\/kick(\/.+)$/);
    if (proxyMatch) {
      const kickPath = proxyMatch[1];
      // Only allow safe read-only API paths
      if (!/^\/(api\/v1|api\/v2|stream)\//.test(kickPath))
        return new Response('Forbidden', { status: 403, headers: CORS_HEADERS });
      const targetUrl = 'https://kick.com' + kickPath + (url.search || '');
      const upstreamResp = await fetch(targetUrl, {
        headers: {
          'Accept':          'application/json',
          'Accept-Language': 'en-US,en;q=0.9',
          'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
          'Referer':         'https://kick.com/',
          'Origin':          'https://kick.com',
        },
      });
      const body = await upstreamResp.text();
      return new Response(body, {
        status: upstreamResp.status,
        headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
      });
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
