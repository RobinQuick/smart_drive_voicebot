// Netlify Function: proxy
// Proxies requests from /api/* to a configured backend origin.
// Set env var BACKEND_ORIGIN, e.g. https://your-backend.example.com

export async function handler(event) {
  const origin = process.env.BACKEND_ORIGIN;
  if (!origin) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "BACKEND_ORIGIN not set" }),
      headers: { 'Content-Type': 'application/json' }
    };
  }

  try {
    // Derive path to forward (strip Netlify function prefix)
    const prefix = '/.netlify/functions/proxy';
    const path = (event.path || '').startsWith(prefix)
      ? event.path.slice(prefix.length)
      : '/';

    // Reconstruct query string
    const qs = event.rawQuery ? `?${event.rawQuery}` : '';

    // Build target URL
    const url = new URL(path + qs, origin).toString();

    // Prepare request init
    const headers = new Headers();
    // Forward most headers, omit hop-by-hop
    for (const [k, v] of Object.entries(event.headers || {})) {
      if (!k) continue;
      const lk = k.toLowerCase();
      if ([
        'host','connection','content-length','accept-encoding','x-forwarded-for',
        'x-forwarded-proto','x-nf-client-connection-ip'
      ].includes(lk)) continue;
      headers.set(k, v);
    }

    let body = undefined;
    if (event.body) {
      body = event.isBase64Encoded ? Buffer.from(event.body, 'base64') : event.body;
    }

    const resp = await fetch(url, {
      method: event.httpMethod || 'GET',
      headers,
      body,
      redirect: 'manual'
    });

    // Collect response headers
    const respHeaders = {};
    for (const [k, v] of resp.headers) {
      // Avoid setting forbidden headers
      if (k.toLowerCase() === 'content-encoding') continue;
      respHeaders[k] = v;
    }

    const buf = Buffer.from(await resp.arrayBuffer());
    return {
      statusCode: resp.status,
      headers: respHeaders,
      body: buf.toString('base64'),
      isBase64Encoded: true
    };
  } catch (err) {
    return {
      statusCode: 502,
      body: JSON.stringify({ error: 'Proxy error', message: err?.message || String(err) }),
      headers: { 'Content-Type': 'application/json' }
    };
  }
}

