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
// The install / activate handlers clean up old SW caches from
// previous Monitor versions so a beta-to-stable upgrade never
// strands the browser on a cached old shell.
// ==========================================================

const SW_VERSION = 'proxmenux-monitor-v1';

self.addEventListener('install', (event) => {
  // Take over as soon as installed; no skipWaiting handshake.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Wipe any cache name that isn't ours — survives renames /
    // version bumps without piling up stale entries.
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n !== SW_VERSION).map((n) => caches.delete(n))
    );
    await self.clients.claim();
  })());
});

// Network-only fetch. The SW exists so Chrome marks the site as
// installable; we deliberately do not serve cached responses.
self.addEventListener('fetch', (event) => {
  // Let the browser handle it normally — no respondWith → no cache.
  return;
});
