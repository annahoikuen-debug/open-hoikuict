/**
 * open-hoikuict オフライン耐性送信キュー (IndexedDB)
 * 登降園キオスク・午睡チェック・出欠確認などの POST をネットワーク断時にローカル退避し、
 * オンライン復帰時に idempotency_key 付きで自動再送する。
 */
(function (global) {
  "use strict";

  const DB_NAME = "open_hoikuict_offline_queue";
  const STORE_NAME = "pending_requests";
  const DB_VERSION = 1;

  function openQueueDb() {
    return new Promise((resolve, reject) => {
      if (!global.indexedDB) {
        reject(new Error("IndexedDB is not supported"));
        return;
      }
      const req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: "id" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function uuidV4() {
    if (global.crypto && typeof global.crypto.randomUUID === "function") {
      return global.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  async function enqueueRequest(url, method, bodyObj, headersObj) {
    const db = await openQueueDb();
    const idempotencyKey = uuidV4();
    const record = {
      id: idempotencyKey,
      url: url,
      method: method || "POST",
      body: bodyObj || {},
      headers: Object.assign(
        {
          "Content-Type": "application/json",
          "X-Idempotency-Key": idempotencyKey,
        },
        headersObj || {}
      ),
      client_recorded_at: new Date().toISOString(),
      retry_count: 0,
    };

    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(record);
      tx.oncomplete = () => resolve(record);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function listPending() {
    const db = await openQueueDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function removePending(id) {
    const db = await openQueueDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function sendWithOfflineFallback(url, bodyObj, headersObj) {
    const idempotencyKey = uuidV4();
    const headers = Object.assign(
      {
        "Content-Type": "application/json",
        "X-Idempotency-Key": idempotencyKey,
      },
      headersObj || {}
    );
    const payload = Object.assign({}, bodyObj || {}, {
      idempotency_key: idempotencyKey,
      client_recorded_at: new Date().toISOString(),
    });

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
      });
      if (res.status >= 500) {
        throw new Error("Server error: " + res.status);
      }
      return { ok: res.ok, queued: false, status: res.status, response: res };
    } catch (_err) {
      const queued = await enqueueRequest(url, "POST", payload, headers);
      return { ok: true, queued: true, id: queued.id };
    }
  }

  async function flushQueue() {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      return { sent: 0, remaining: (await listPending()).length };
    }
    const items = await listPending();
    let sent = 0;
    for (const item of items) {
      try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const reqHeaders = Object.assign({}, item.headers || {});
        if (csrfMeta && csrfMeta.content) {
          reqHeaders["X-CSRF-Token"] = csrfMeta.content;
        }
        const res = await fetch(item.url, {
          method: item.method || "POST",
          headers: reqHeaders,
          body: JSON.stringify(item.body),
        });
        if (res.ok || (res.status >= 400 && res.status < 500 && res.status !== 403)) {
          await removePending(item.id);
          sent += 1;
        }
      } catch (_err) {
        // 次回リトライへ残す
      }
    }
    const remaining = (await listPending()).length;
    return { sent: sent, remaining: remaining };
  }

  if (typeof global.addEventListener === "function") {
    global.addEventListener("online", () => {
      flushQueue().catch(() => {});
    });
  }

  global.HoikuOfflineQueue = {
    sendWithOfflineFallback: sendWithOfflineFallback,
    flushQueue: flushQueue,
    listPending: listPending,
  };
})(window);
