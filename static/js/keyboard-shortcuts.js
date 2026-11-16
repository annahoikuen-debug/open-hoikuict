/**
 * キーボードショートカット (open-hoikuict Staff Console)
 * 
 * 2ストローク操作:
 *   g d: ホーム (ダッシュボード)
 *   g a: 出欠一覧・打刻
 *   g c: 日次連絡帳
 *   g n: お知らせ管理
 * 
 * 単体キー:
 *   ?: ショートカット一覧ヘルプを表示
 *   Esc: ダイアログ・モーダルを閉じる
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // 職員サイドバーが存在する場合のみ有効化
    if (!document.getElementById("staff-sidebar")) {
      return;
    }

    var keyBuffer = "";
    var bufferTimer = null;

    var routes = {
      d: "/",
      a: "/attendance",
      c: "/daily-contacts",
      n: "/notices"
    };

    function isInputFocused() {
      var el = document.activeElement;
      if (!el) return false;
      var tag = el.tagName ? el.tagName.toLowerCase() : "";
      return (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        el.isContentEditable ||
        (el.getAttribute && el.getAttribute("role") === "textbox")
      );
    }

    function showShortcutModal() {
      var modal = document.getElementById("shortcut-help-modal");
      if (modal && typeof modal.showModal === "function") {
        modal.showModal();
      }
    }

    function closeShortcutModal() {
      var modal = document.getElementById("shortcut-help-modal");
      if (modal && typeof modal.close === "function" && modal.open) {
        modal.close();
      }
    }

    document.addEventListener("keydown", function (e) {
      if (isInputFocused()) {
        return;
      }

      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        showShortcutModal();
        return;
      }

      if (e.key === "Escape") {
        closeShortcutModal();
        return;
      }

      if (e.key === "g" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        keyBuffer = "g";
        clearTimeout(bufferTimer);
        bufferTimer = setTimeout(function () {
          keyBuffer = "";
        }, 1000);
        return;
      }

      if (keyBuffer === "g") {
        var key = e.key.toLowerCase();
        if (routes[key]) {
          e.preventDefault();
          keyBuffer = "";
          window.location.href = routes[key];
        }
      }
    });

    // 閉じるボタンのイベント紐付け
    var closeBtn = document.getElementById("shortcut-modal-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeShortcutModal);
    }
  });
})();
