// ==========================================================
// ProxMenux Monitor — Service Worker
// ==========================================================
// Minimal SW whose only job is to make Chrome (Android) treat
// the Monitor as an installable PWA. The Monitor lives on the
// operator's LAN, hits a self-signed HTTPS endpoint and has
// ZERO offline value (every page calls /api/* over the wire),
// so we do NOT cache pages or API responses — caching them
// would only cause stale-data bugs after an AppImage update.
//
// The install / activate handlers wipe every cache in Cache
// Storage (no allow-list) so stale entries from any previous
// Monitor version — including ones that shared this SW's
// version name — cannot survive an upgrade and haunt the
// dashboard as frozen `/api/*` responses.
// ==========================================================

const SW_VERSION = 'proxmenux-monitor-v2';

self.addEventListener('install', (event) => {
  // Take over as soon as installed; no skipWaiting handshake.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Scorched earth: wipe EVERY cache, regardless of name. This
    // SW never writes to Cache Storage, so nothing here should
    // ever be authoritative. The previous version kept caches
    // that matched SW_VERSION exactly, which stranded old cached
    // /api/* responses across upgrades and manifested as a
    // dashboard that never refreshed until the user manually
    // cleared Cache Storage from DevTools.
    try {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    } catch (_) {
      // caches API unavailable — nothing to clean.
    }
    await self.clients.claim();
  })());
});

// Network-only fetch. The SW exists so Chrome marks the site as
// installable; we deliberately do not serve cached responses.
self.addEventListener('fetch', (event) => {
  // Let the browser handle it normally — no respondWith → no cache.
  return;
});
