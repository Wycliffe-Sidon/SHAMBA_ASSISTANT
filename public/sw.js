self.addEventListener("install", event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", event => {
  event.respondWith(
    caches.open("shamba-assistant-v1").then(async cache => {
      try {
        const fresh = await fetch(event.request);
        if (event.request.method === "GET" && fresh.ok) {
          cache.put(event.request, fresh.clone());
        }
        return fresh;
      } catch (_error) {
        const cached = await cache.match(event.request);
        if (cached) {
          return cached;
        }
        throw _error;
      }
    })
  );
});
