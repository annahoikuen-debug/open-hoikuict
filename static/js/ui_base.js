/**
 * ui_base.js - 商用品質 UI 基礎ライブラリ (Phase 5.2).
 * 
 * 責務:
 * 1. フォーム二重送信防止（連打による二重請求・重複打刻・二重保存の物理的遮断）
 * 2. HTMX 通信時の CSRF トークン自動注入とローディング状態制御
 * 3. アクセシビリティ・通知フィードバックの統一
 */
(function() {
  'use strict';

  // 1. 全フォームへの二重送信防止ガード
  document.addEventListener('submit', function(e) {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;

    // 二重送信防止を除外したいフォーム（data-allow-resubmit="true"）
    if (form.getAttribute('data-allow-resubmit') === 'true') return;

    // 既に送信処理中の場合は重複送信を阻止
    if (form.dataset.submitting === 'true') {
      e.preventDefault();
      return false;
    }

    form.dataset.submitting = 'true';

    // 送信ボタン群を disabled 化し、スピナーまたはローディング表示を付与
    const submitButtons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    submitButtons.forEach(btn => {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add('opacity-75', 'cursor-not-allowed');

      if (btn.tagName === 'BUTTON') {
        btn.innerHTML = `
          <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          処理中...
        `;
      }
    });

    // 10秒経過しても応答がない場合は安全のため disabled を解除
    setTimeout(() => {
      form.dataset.submitting = 'false';
      submitButtons.forEach(btn => {
        btn.disabled = false;
        btn.classList.remove('opacity-75', 'cursor-not-allowed');
        if (btn.dataset.originalHtml) {
          btn.innerHTML = btn.dataset.originalHtml;
        }
      });
    }, 10000);
  });

  // 2. HTMX イベント連携（CSRF トークン注入 & ボタン復元）
  document.addEventListener('htmx:configRequest', function(evt) {
    // Cookie または DOM 内の CSRF トークンをヘッダーに自動付与
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
    if (csrfToken) {
      evt.detail.headers['X-CSRF-Token'] = csrfToken;
    }
  });

  document.addEventListener('htmx:afterRequest', function(evt) {
    const elt = evt.detail.elt;
    if (elt && elt.form) {
      elt.form.dataset.submitting = 'false';
      const submitButtons = elt.form.querySelectorAll('button[type="submit"], input[type="submit"]');
      submitButtons.forEach(btn => {
        btn.disabled = false;
        btn.classList.remove('opacity-75', 'cursor-not-allowed');
        if (btn.dataset.originalHtml) {
          btn.innerHTML = btn.dataset.originalHtml;
        }
      });
    }
  });
})();
