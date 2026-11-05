const CACHE_NAME = 'guardian-kiosk-cache-v1';
const PRECACHE_ASSETS = [
    '/guardian/terminal',
    '/guardian/manifest.webmanifest',
    '/guardian/assets/icon-192.png',
    '/guardian/assets/icon-512.png',
    '/guardian/assets/terminal.js?v=20260924',
    '/static/js/tailwindcss.js',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_ASSETS)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
        )).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    // 同オリジンかつ guardian スコープ内のリクエストをキャッシュ優先
    if (url.origin === self.location.origin && url.pathname.startsWith('/guardian/')) {
        event.respondWith(
            caches.match(event.request).then(cached => {
                if (cached) return cached;
                return fetch(event.request).then(response => {
                    if (response && response.status === 200 && response.type === 'basic') {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
    }
});
