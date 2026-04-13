/**
 * Cloudflare Worker — serves R2 bucket as a browsable Kodi repository.
 * Deploy to kodi.zales.dev with R2 binding named BUCKET.
 */

export default {
  async fetch(request, env) {
    const url  = new URL(request.url);
    let path   = decodeURIComponent(url.pathname);

    // Strip leading slash
    const key = path.replace(/^\//, '');

    // --- Serve file directly ---
    if (key && !key.endsWith('/')) {
      const obj = await env.BUCKET.get(key);
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
      headers.set('Cache-Control', 'public, max-age=300');
      return new Response(obj.body, { headers });
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
