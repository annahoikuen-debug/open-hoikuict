/**
 * 職員オンボーディングツアー (open-hoikuict Staff Console)
 * 初回ログイン職員に主要機能（ホーム・出席・連絡帳・お知らせ・設定）を案内する。
 */
(function () {
  "use strict";

  var STORAGE_KEY = "hoikuict_onboarding_completed";

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
      desc: "保護者から届いた生活記録やお迎え予定を確認し、返信を作成・送信できます。"
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
      title: "設定",
      desc: "開園時間や延長保育ルール、ツアーの再表示などは設定画面からいつでも行えます。"
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
  }

  window.restartOnboardingTour = function () {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    createTourElements();
    showStep(0);
  };

  document.addEventListener("DOMContentLoaded", function () {
    // 職員画面かつホーム画面でのみ初回自動起動
    if (!document.getElementById("staff-sidebar")) return;

    var isHome = window.location.pathname === "/" || window.location.pathname === "/staff/portal";
    if (!isHome) return;

    try {
      var completed = localStorage.getItem(STORAGE_KEY);
      if (!completed) {
        // 少し遅延させて自然に開始
        setTimeout(function () {
          createTourElements();
          showStep(0);
        }, 600);
      }
    } catch (e) {}
  });
})();
