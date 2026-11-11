// Penny Run service worker: app shell from cache, data fresh from the network when possible.
const VERSION = 'penny-run-v1';
const SHELL = ['./', 'index.html', 'app.css', 'app.js', 'manifest.webmanifest', 'icons/icon-192.png'];
self.addEventListener('install', e => e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  // network first (so updates show up right away), cache as the offline fallback
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(url.pathname.endsWith('data.json') ? 'data.json' : e.request, copy)); }
    return r;
  }).catch(() => caches.match(url.pathname.endsWith('data.json') ? 'data.json' : e.request, { ignoreSearch: true })
    .then(r => r || caches.match('index.html'))));
});
