const CACHE_NAME = "pixelproof-v1";

self.addEventListener("install", event => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.map(k => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);

  // ❌ NEVER cache API calls
  if (url.pathname.startsWith("/api")) return;

  // ❌ NEVER cache POST requests
  if (req.method !== "GET") return;

  // Cache-first for static assets
  event.respondWith(
    caches.match(req).then(cached => {
      return (
        cached ||
        fetch(req)
          .then(res => {
            const copy = res.clone();
            caches.open(CACHE_NAME).then(cache => {
              cache.put(req, copy);
            });
            return res;
          })
          .catch(() => cached)
      );
    })
  );
});
