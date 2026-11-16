/**
 * attendance-offline.js - 職員出席管理のオフライン検知 & キャッシュ連携 (P5-2)
 */
(function() {
  'use strict';

  // 1. Service Workerの登録
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/js/staff-offline-worker.js')
        .then((reg) => {
          console.debug('[OfflineWorker] ServiceWorker registration successful:', reg.scope);
        })
        .catch((err) => {
          console.warn('[OfflineWorker] ServiceWorker registration failed:', err);
        });
    });
  }

  // 2. オフラインバナーの制御
  function createOrUpdateBanner(isOffline) {
    let banner = document.getElementById('offline-status-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'offline-status-banner';
      banner.className = 'fixed top-0 left-0 right-0 z-50 px-4 py-2 text-center text-xs font-semibold shadow-md transition-all duration-300';
      document.body.prepend(banner);
    }

    if (isOffline) {
      banner.className = 'fixed top-0 left-0 right-0 z-50 px-4 py-2 text-center text-xs font-semibold shadow-md bg-amber-500 text-white flex items-center justify-center gap-2';
      banner.innerHTML = '<span>📡</span> <span>オフライン表示中: 最新キャッシュされた名簿を表示しています（打刻はオンライン復帰後に実行してください）</span>';
      banner.style.display = 'flex';
    } else {
      banner.className = 'fixed top-0 left-0 right-0 z-50 px-4 py-2 text-center text-xs font-semibold shadow-md bg-emerald-600 text-white flex items-center justify-center gap-2';
      banner.innerHTML = '<span>✅</span> <span>オンラインに復帰しました</span>';
      setTimeout(() => {
        banner.style.display = 'none';
      }, 3000);
    }
  }

  window.addEventListener('online', () => createOrUpdateBanner(false));
  window.addEventListener('offline', () => createOrUpdateBanner(true));

  // 初期ロード時にもしオフラインならバナー表示
  if (!navigator.onLine) {
    createOrUpdateBanner(true);
  }

  // 3. 当日の出席名簿データをローカルキャッシュ
  const table = document.querySelector('table');
  if (table && window.localStorage) {
    try {
      const todayKey = 'open_hoiku_attendance_cache_' + (new Date().toISOString().slice(0, 10));
      // オンラインならテーブルHTMLをローカル保存
      if (navigator.onLine) {
        window.localStorage.setItem(todayKey, table.outerHTML);
      }
    } catch (e) {
      console.warn('[OfflineWorker] Failed to cache table to localStorage:', e);
    }
  }
})();
