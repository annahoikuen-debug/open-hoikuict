/**
 * kiosk_sync.js - キオスク・端末打刻のオフラインキュー & 冪等同期 (Phase 5.1).
 * 
 * ネットワーク断（電波瞬断・Wi-Fi切断）時でも打刻を失わず、
 * IndexedDB に idempotency_key と共にキューイングし、オンライン復帰時に自動再送・同期する。
 */
(function() {
  'use strict';

  const DB_NAME = 'HoikuIctKioskDB';
  const DB_VERSION = 1;
  const STORE_NAME = 'punch_queue';

  function openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'idempotency_key' });
          store.createIndex('timestamp', 'timestamp', { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  // キューに追加
  async function enqueuePunch(punchData) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const item = {
        ...punchData,
        idempotency_key: punchData.idempotency_key || (crypto.randomUUID ? crypto.randomUUID() : 'kiosk_' + Date.now() + '_' + Math.random().toString(36).slice(2)),
        timestamp: Date.now(),
        retry_count: 0,
      };
      const req = store.put(item);
      req.onsuccess = () => resolve(item);
      req.onerror = () => reject(req.error);
    });
  }

  // 保留中キューの取得
  async function getPendingPunches() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  // 送信完了した打刻を削除
  async function removePunch(idempotencyKey) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.delete(idempotencyKey);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }

  // オンライン復帰時の自動再送同期
  async function syncPendingPunches() {
    if (!navigator.onLine) return;

    try {
      const pending = await getPendingPunches();
      if (pending.length === 0) return;

      console.info(`[KioskSync] 未同期打刻 ${pending.length} 件の自動送信を開始します`);

      for (const punch of pending) {
        try {
          const formData = new FormData();
          formData.append('date', punch.date);
          formData.append('idempotency_key', punch.idempotency_key);
          if (punch.expected_version) {
            formData.append('expected_version', punch.expected_version);
          }

          const response = await fetch(punch.endpoint, {
            method: 'POST',
            body: formData,
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
            },
          });

          // 2xx または 3xx は成功（既に冪等処理済み含む）
          if (response.ok || (response.status >= 300 && response.status < 400)) {
            await removePunch(punch.idempotency_key);
            console.info(`[KioskSync] 打刻同期成功: ${punch.idempotency_key}`);
          }
        } catch (err) {
          console.warn(`[KioskSync] 打刻同期リトライ待機 (${punch.idempotency_key}):`, err);
        }
      }
    } catch (e) {
      console.warn('[KioskSync] 同期処理エラー:', e);
    }
  }

  window.addEventListener('online', syncPendingPunches);
  window.addEventListener('load', syncPendingPunches);

  // グローバル公開
  window.KioskSync = {
    enqueuePunch,
    syncPendingPunches,
  };
})();
