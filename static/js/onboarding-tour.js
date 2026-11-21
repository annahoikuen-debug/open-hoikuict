/**
 * 職員オンボーディングツアー (open-hoikuict Staff Console)
 * 初回ログイン職員に主要機能（ホーム・出席・連絡帳・お知らせ・設定）を案内する。
 */
(function () {
  "use strict";

  var STORAGE_KEY = "hoikuict_onboarding_completed";
  var PROGRESS_KEY = "hoikuict_onboarding_progress";

  var TOUR_STEPS = [
    {
      step: 1,
      selector: '[data-tour-step="1"]',
      title: "ホーム (ダッシュボード)",
      desc: "本日の登園状況や未返信の連絡帳など、園全体の重要アラートが一目で把握できます。"
    },
    {
      step: 2,
      selector: '[data-tour-step="2"]',
      title: "出欠一覧・一括打刻",
      desc: "毎朝の登降園の記録や出欠状況を確認できます。複数園児を選択した一括打刻もここから行えます。"
    },
    {
      step: 3,
      selector: '[data-tour-step="3"]',
      title: "日次連絡帳",
      desc: "保護者から届いた生活記録やお迎え予定を確認し、返信を作成・承認・送信できます。"
    },
    {
      step: 4,
      selector: '[data-tour-step="4"]',
      title: "お知らせ管理",
      desc: "園だよりや緊急連絡をクラス別または全園児の保護者へ一斉配信（Push通知）できます。"
    },
    {
      step: 5,
      selector: '[data-tour-step="5"]',
      title: "指導計画 (日案・月案)",
      desc: "文例AIサジェストや前日振り返り連携を活用し、環境図付きの日案・月案を作成・A4印刷できます。"
    },
    {
      step: 6,
      selector: '[data-tour-step="6"]',
      title: "シフト作成・勤怠",
      desc: "法令配置基準を自動充足するAIソルバーを活用し、有休・希望休を考慮したシフトを最適化します。"
    },
    {
      step: 7,
      selector: '[data-tour-step="7"]',
      title: "請求・口座振替",
      desc: "延長保育料や給食日割りを自動計算。確定前検算や全銀電文生成をワンストップで実行できます。"
    },
    {
      step: 8,
      selector: '[data-tour-step="8"]',
      title: "施設設定＆診断",
      desc: "基本開園時間や料金マスタ、設定ヘルスチェック診断をいつでも確認・修正できます。"
    }
  ];

  var currentStepIdx = 0;
  var overlayEl = null;
  var popoverEl = null;

  function createTourElements() {
    if (overlayEl) return;

    // 半透明背景
    overlayEl = document.createElement("div");
    overlayEl.id = "hoikuict-tour-overlay";
    overlayEl.style.cssText =
      "position:fixed;inset:0;background:rgba(15,23,42,0.7);z-index:9000;display:none;transition:opacity 0.2s ease;";
    document.body.appendChild(overlayEl);

    // ポップオーバーカード
    popoverEl = document.createElement("div");
    popoverEl.id = "hoikuict-tour-popover";
    popoverEl.style.cssText =
      "position:fixed;z-index:9002;width:320px;background:#ffffff;border-radius:12px;padding:18px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.3);display:none;transition:top 0.2s ease,left 0.2s ease;font-family:inherit;";
    popoverEl.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;">' +
      '  <span id="tour-badge" style="font-size:11px;font-weight:700;background:#e0e7ff;color:#4338ca;padding:2px 8px;border-radius:9999px;">Step 1/5</span>' +
      '  <button id="tour-skip-btn" style="background:none;border:none;color:#94a3b8;font-size:12px;cursor:pointer;">✕ スキップ</button>' +
      "</div>" +
      '<h4 id="tour-title" style="margin:8px 0 4px;font-size:14px;font-weight:700;color:#0f172a;"></h4>' +
      '<p id="tour-desc" style="margin:0;font-size:12px;color:#475569;line-height:1.5;"></p>' +
      '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center;">' +
      '  <button id="tour-prev-btn" style="background:none;border:none;color:#64748b;font-size:12px;font-weight:600;cursor:pointer;">前へ</button>' +
      '  <button id="tour-next-btn" style="background:#4f46e5;color:#ffffff;border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">次へ →</button>' +
      "</div>";
    document.body.appendChild(popoverEl);

    document.getElementById("tour-skip-btn").addEventListener("click", endTour);
    document.getElementById("tour-prev-btn").addEventListener("click", prevStep);
    document.getElementById("tour-next-btn").addEventListener("click", nextStep);
  }

  function showStep(idx) {
    if (idx < 0 || idx >= TOUR_STEPS.length) return;
    currentStepIdx = idx;

    // 前のハイライト解除
    document.querySelectorAll(".hoikuict-tour-highlight").forEach(function (el) {
      el.classList.remove("hoikuict-tour-highlight");
      el.style.boxShadow = "";
      el.style.position = "";
      el.style.zIndex = "";
      el.style.borderRadius = "";
    });

    var step = TOUR_STEPS[idx];
    var targetEl = document.querySelector(step.selector);

    if (!targetEl) {
      // 画面に対象が無い場合はスキップして次へ
      if (idx + 1 < TOUR_STEPS.length) {
        showStep(idx + 1);
      } else {
        endTour();
      }
      return;
    }

    targetEl.classList.add("hoikuict-tour-highlight");
    targetEl.style.position = "relative";
    targetEl.style.zIndex = "9001";
    targetEl.style.boxShadow = "0 0 0 4px #4f46e5, 0 0 0 9999px rgba(15,23,42,0.7)";
    targetEl.style.borderRadius = "8px";

    var rect = targetEl.getBoundingClientRect();
    overlayEl.style.display = "block";
    popoverEl.style.display = "block";

    // 位置計算（右側に余白があれば右、なければ下）
    var popLeft = rect.right + 16;
    var popTop = rect.top;

    if (popLeft + 320 > window.innerWidth) {
      popLeft = Math.max(16, rect.left);
      popTop = rect.bottom + 16;
    }
    if (popTop + 200 > window.innerHeight) {
      popTop = Math.max(16, window.innerHeight - 220);
    }

    popoverEl.style.left = popLeft + "px";
    popoverEl.style.top = popTop + "px";

    document.getElementById("tour-badge").textContent = "Step " + (idx + 1) + "/" + TOUR_STEPS.length;
    document.getElementById("tour-title").textContent = step.title;
    document.getElementById("tour-desc").textContent = step.desc;
    try { localStorage.setItem(PROGRESS_KEY, String(idx + 1)); } catch (e) {}

    document.getElementById("tour-prev-btn").style.visibility = idx === 0 ? "hidden" : "visible";
    document.getElementById("tour-next-btn").textContent =
      idx === TOUR_STEPS.length - 1 ? "ツアー完了 🎉" : "次へ →";
  }

  function nextStep() {
    if (currentStepIdx < TOUR_STEPS.length - 1) {
      showStep(currentStepIdx + 1);
    } else {
      endTour();
    }
  }

  function prevStep() {
    if (currentStepIdx > 0) {
      showStep(currentStepIdx - 1);
    }
  }

  function endTour() {
    if (overlayEl) overlayEl.style.display = "none";
    if (popoverEl) popoverEl.style.display = "none";
    document.querySelectorAll(".hoikuict-tour-highlight").forEach(function (el) {
      el.classList.remove("hoikuict-tour-highlight");
      el.style.boxShadow = "";
      el.style.position = "";
      el.style.zIndex = "";
      el.style.borderRadius = "";
    });
    try {
      localStorage.setItem(STORAGE_KEY, "true");
    } catch (e) {}

    // P1-2: サーバ側への完了状態永続化
    try {
      var formData = new FormData();
      formData.append("tour_key", "staff_console_tour");
      fetch("/settings/tour/complete", {
        method: "POST",
        body: formData,
        credentials: "same-origin"
      }).catch(function () {});
    } catch (e) {}
  }

  window.restartOnboardingTour = function (startStep) {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}

    // P1-2: サーバ側の完了状態リセット
    try {
      var formData = new FormData();
      formData.append("tour_key", "staff_console_tour");
      fetch("/settings/tour/reset", {
        method: "POST",
        body: formData,
        credentials: "same-origin"
      }).catch(function () {});
    } catch (e) {}

    createTourElements();
    showStep(startStep == null ? 0 : Math.max(0, Math.min(TOUR_STEPS.length - 1, Number(startStep) || 0)));
  };

  window.startOnboardingTourFrom = function (stepIdx) {
    createTourElements();
    showStep(Math.max(0, Math.min(TOUR_STEPS.length - 1, Number(stepIdx) || 0)));
  };

  function initTourProgressWidget() {
    var labelEl = document.getElementById("tour-progress-label");
    var resumeBtn = document.getElementById("tour-resume-btn");
    if (!labelEl) return;

    fetch("/settings/tour/status?tour_key=staff_console_tour", { credentials: "same-origin" })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var completed = Boolean(data && data.is_completed);
        var progress = 0;
        try { progress = Math.max(0, Math.min(8, Number(localStorage.getItem(PROGRESS_KEY)) || 0)); } catch (e) {}

        if (completed) {
          labelEl.textContent = "完了済み";
        } else {
          labelEl.textContent = "未完了・進捗 " + progress + "/8";
          if (resumeBtn && progress > 0) {
            resumeBtn.hidden = false;
            resumeBtn.dataset.step = progress;
          }
        }
      })
      .catch(function () {
        // オフライン時など：既存の「ツアーを開始」ボタンのみでフォールバック
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // ツアー進捗ウィジェット（設定画面など）
    initTourProgressWidget();

    // 職員画面かつホーム画面でのみ初回自動起動
    if (!document.getElementById("staff-sidebar")) return;

    var isHome = window.location.pathname === "/" || window.location.pathname === "/staff/portal";
    if (!isHome) return;

    // サーバ側の完了ステータスを確認
    fetch("/settings/tour/status?tour_key=staff_console_tour", { credentials: "same-origin" })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.is_completed) {
          try { localStorage.setItem(STORAGE_KEY, "true"); } catch (e) {}
          return;
        }
        var completed = false;
        try { completed = localStorage.getItem(STORAGE_KEY) === "true"; } catch (e) {}
        if (!completed) {
          setTimeout(function () {
            createTourElements();
            showStep(0);
          }, 600);
        }
      })
      .catch(function () {
        // オフラインまたはエラー時は localStorage をフォールバック
        var completed = false;
        try { completed = localStorage.getItem(STORAGE_KEY) === "true"; } catch (e) {}
        if (!completed) {
          setTimeout(function () {
            createTourElements();
            showStep(0);
          }, 600);
        }
      });
  });
})();
