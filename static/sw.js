const CACHE = 'congreso-ai-v1';
const ASSETS = ['/', '/static/style.css', '/static/app.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Don't cache POST /chat — always network
  if (e.request.method === 'POST') return;

  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
