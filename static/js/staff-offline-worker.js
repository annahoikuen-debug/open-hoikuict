/**
 * staff-offline-worker.js - 職員画面の当日名簿オフライン閲覧キャッシュ Service Worker (P5-2)
 *
 * 朝の登園ピーク時の回線瞬断やWi-Fi障害時でも、
 * キャッシュされた当日出席名簿やアセットを即座に表示可能にします。
 */

const CACHE_NAME = 'open-hoiku-staff-cache-v1';
const PRECACHE_ASSETS = [
  '/static/css/htmx-indicator.css',
  '/attendance',
];

// インストール時にコアアセットをキャッシュ
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('Pre-cache warning (some assets may not exist yet):', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// アクティベーション時に古いキャッシュを整理
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(
        keyList.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// フェッチハンドラ: Network First with Cache Fallback
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // GETリクエスト以外はService Workerではキャッシュせず素通し
  if (req.method !== 'GET') {
    return;
  }

  // 出席管理画面および静的アセットのキャッシュ戦略
  event.respondWith(
    fetch(req)
      .then((networkResponse) => {
        // 成功したレスポンスをキャッシュに複製保存
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(req, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(async () => {
        // ネットワーク切断・タイムアウト時はキャッシュから返却
        const cachedResponse = await caches.match(req);
        if (cachedResponse) {
          return cachedResponse;
        }
        // ルート画面または出席画面のフォールバック
        if (req.mode === 'navigate') {
          const fallback = await caches.match('/attendance');
          if (fallback) {
            return fallback;
          }
        }
        return new Response(
          '<html><head><meta charset="utf-8"><title>オフライン</title></head>' +
          '<body style="font-family: sans-serif; text-align: center; padding: 50px;">' +
          '<h2>📡 オフラインです</h2>' +
          '<p>ネットワーク接続を確認してください。キャッシュ済みの名簿画面へ戻るには再読み込みをお試しください。</p>' +
          '<button onclick="location.reload()" style="padding: 8px 16px; border-radius: 6px; background: #4f46e5; color: white; border: none; cursor: pointer;">再試行</button>' +
          '</body></html>',
          {
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
            status: 503,
            statusText: 'Service Unavailable (Offline)'
          }
        );
      })
  );
});
