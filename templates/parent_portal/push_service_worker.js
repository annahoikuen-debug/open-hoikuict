const CACHE_NAME = 'nusoft-portal-cache-v1';
const PRECACHE_ASSETS = [
  '/static/js/tailwindcss.js',
  '/static/js/htmx.min.js',
  '/parent-portal/manifest.webmanifest',
  '/parent-portal/push-icon.svg'
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
  // キャッシュ対象の静的アセットへのリクエストはキャッシュから優先返却
  const url = new URL(event.request.url);
  if (url.origin === self.location.origin && (url.pathname.startsWith('/static/') || PRECACHE_ASSETS.includes(url.pathname))) {
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
        }
        return response;
      }))
    );
  }
});

self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { payload = {}; }
  const title = payload.title || '保育園から確認のお願い';
  const body = payload.body || '確認が必要な連絡があります。保護者ポータルをご確認ください。';
  const receiptData = {
    target_id: payload.target_id,
    shown_receipt_token: payload.shown_receipt_token
  };
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/parent-portal/push-icon.svg',
    badge: '/parent-portal/push-icon.svg',
    tag: payload.notification_id ? `parent-notification-${payload.notification_id}` : undefined,
    data: {
      action_url: safeActionUrl(payload.action_url),
      target_id: payload.target_id,
      clicked_receipt_token: payload.clicked_receipt_token
    }
  }).then(() => postReceipt(receiptData, 'shown')));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const actionUrl = safeActionUrl(event.notification.data?.action_url);
  event.waitUntil((async () => {
    await postReceipt(event.notification.data, 'clicked');
    const absoluteUrl = new URL(actionUrl, self.location.origin).href;
    const windows = await clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of windows) {
      let clientUrl;
      try { clientUrl = new URL(client.url); } catch (_) { continue; }
      if (clientUrl.origin !== self.location.origin || !clientUrl.pathname.startsWith('/parent-portal/')) continue;
      try {
        const navigated = 'navigate' in client ? await client.navigate(absoluteUrl) : client;
        return await (navigated || client).focus();
      } catch (_) {
        // Android Chrome may reject navigation of a stale window client. Try another
        // portal window and finally open a new one below.
      }
    }
    const opened = await clients.openWindow(absoluteUrl);
    return opened && 'focus' in opened ? opened.focus() : opened;
  })());
});

function safeActionUrl(value) {
  return typeof value === 'string' && value.startsWith('/parent-portal/') ? value : '/parent-portal/';
}

async function postReceipt(data, eventName) {
  const token = data?.[`${eventName}_receipt_token`];
  const targetId = data?.target_id;
  if (!token || !Number.isInteger(targetId)) return;
  try {
    await fetch(`/parent-portal/push/receipts/${targetId}/${eventName}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token})
    });
  } catch (_) {
    // Receipt failure must not prevent notification navigation.
  }
}
