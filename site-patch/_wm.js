// Tab 2026-11-12: "Yidplus.com" watermark, server side.
// The browser burns the mark into photos before upload (js/state.js watermarkImage) and
// tags them with a 5-byte trailer "YPWM1". Everything else that arrives here unmarked
// (every video, and photos from the Android app or an old browser) is queued in R2 under
// wmq/ and burned in by the free GitHub Actions runner in the public repo
// 848848448/yidplus-watermark (site.yml, every 5 min), which replaces the R2 object in
// place under the SAME key, so no database row changes. No D1 reads or writes at all.
// Endpoints for the runner: functions/api/wm/[[path]].js (key: env WM_KEY).

const VIDEO_EXT = /\.(mp4|mov|webm|mkv|m4v|avi|3gp)$/i;
const IMAGE_EXT = /\.(jpe?g|png|webp|bmp|heic|heif|avif)$/i;
export const WM_TRAILER = 'YPWM1';

// 'video' | 'image' | null  (GIFs and stickers are left alone: redrawing loses animation)
export function wmKind(contentType, name) {
  const ct = String(contentType || '').toLowerCase();
  const nm = String(name || '').toLowerCase();
  if (ct === 'image/gif' || /\.gif$/.test(nm) || ct === 'image/svg+xml') return null;
  if (ct.startsWith('video/') || (!ct.startsWith('image/') && VIDEO_EXT.test(nm))) return 'video';
  if (ct.startsWith('image/') || IMAGE_EXT.test(nm)) return 'image';
  return null;
}

export function hasWmTrailer(buf) {
  try {
    if (!buf) return false;
    const u = new Uint8Array(buf instanceof ArrayBuffer ? buf : (buf.buffer || buf));
    const n = u.length;
    if (n < 5) return false;
    return String.fromCharCode(u[n - 5], u[n - 4], u[n - 3], u[n - 2], u[n - 1]) === WM_TRAILER;
  } catch (e) { return false; }
}

// Should this upload be queued? bytes = the ArrayBuffer when the caller has it (null for streams).
export function wmNeeded(contentType, name, bytes) {
  const kind = wmKind(contentType, name);
  if (!kind) return null;
  if (kind === 'image' && bytes && hasWmTrailer(bytes)) return null; // already burned by the browser
  return kind;
}

// R2 put options with the "pending" flag (media endpoint serves pending objects without
// the 1-year immutable cache, so the marked copy replaces it for everyone).
export function wmPutMeta(kind) {
  return kind ? { customMetadata: { wm: 'pending' } } : {};
}

// Queue a stored object. Never throws (an upload must never fail because of the watermark).
export async function wmEnqueue(env, key, kind, contentType, ctx) {
  try {
    if (!kind || !key || !env || !env.MY_BUCKET) return;
    const id = Date.now() + '_' + crypto.randomUUID().slice(0, 8);
    await env.MY_BUCKET.put('wmq/' + id + '.json', JSON.stringify({
      key, kind, ct: contentType || '', at: new Date().toISOString(), tries: 0,
    }), { httpMetadata: { contentType: 'application/json' } });
  } catch (e) { /* ignore: the file is still uploaded, just unmarked */ return; }
  // Start the runner now (debounced). With ctx (the Pages Function context) it runs after the
  // response is sent; without it, it adds at most ~3 s to this upload and never fails it.
  if (ctx && typeof ctx.waitUntil === 'function') ctx.waitUntil(wmKick(env));
  else await wmKick(env);
}

// Tab 2026-11-12 (event trigger, NOT live until GH_WM_TOKEN is set): right after a file is
// queued, ask GitHub to start the watermark run now instead of waiting for the */5 schedule
// (which GitHub fires only every few hours on that repo). Debounced through one tiny R2 object
// (wmkick/last): at most one call per WM_KICK_EVERY_MS. A run started by a call keeps looking
// for ~150 s after the queue is empty (site.yml), which is longer than the debounce window,
// so uploads that skip the call are still picked up by that run. GitHub also keeps at most one
// pending run in the "site-watermark" concurrency group, so extra calls collapse on their own.
// Token: a fine-grained GitHub token with Actions read/write on 848848448/yidplus-watermark ONLY,
// stored as the Pages secret GH_WM_TOKEN. No token = this does nothing. Never throws.
const WM_KICK_EVERY_MS = 2 * 60 * 1000;
const WM_DISPATCH_URL = 'https://api.github.com/repos/848848448/yidplus-watermark/actions/workflows/site.yml/dispatches';

export async function wmKick(env) {
  try {
    if (!env || !env.GH_WM_TOKEN || !env.MY_BUCKET) return;
    const now = Date.now();
    const last = await env.MY_BUCKET.head('wmkick/last');
    const lastAt = last && last.customMetadata ? Number(last.customMetadata.at || 0) : 0;
    if (lastAt && now - lastAt < WM_KICK_EVERY_MS) return;          // a run was asked for < 2 min ago
    await env.MY_BUCKET.put('wmkick/last', '', { customMetadata: { at: String(now) } });
    const r = await fetch(WM_DISPATCH_URL, {
      method: 'POST',
      headers: {
        'authorization': 'Bearer ' + env.GH_WM_TOKEN,
        'accept': 'application/vnd.github+json',
        'x-github-api-version': '2022-11-28',
        'user-agent': 'yidplus-wm-kick',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
      signal: AbortSignal.timeout(3000),
    });
    if (r.status !== 204) {
      // let the next upload try again instead of waiting out the window
      await env.MY_BUCKET.delete('wmkick/last');
    }
  } catch (e) { /* ignore: the 5-minute schedule is still the backup */ }
}
