/* ===================================================================
   nusoft Landing Page Interactive Logic
   Theme, Simulator, Tabs, Accordion, Modal & Animation
   =================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initNavbarScroll();
  initMobileNav();
  initHeroDemo();
  initSimulator();
  initRoiSimulator();
  initFeatureTabs();
  initFaqAccordion();
  initModal();
  initScrollReveal();
  initStatCounters();
  initScrollSpy();
  initFloatingCta();
});

/* -------------------------------------------------------------
   1. Theme Toggle (Dark / Light)
   ------------------------------------------------------------- */
function initTheme() {
  const toggleBtn = document.getElementById('themeToggleBtn');
  const themeIcon = document.getElementById('themeIcon');
  const savedTheme = localStorage.getItem('nusoft-theme') || 'dark';

  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeIcon(savedTheme, themeIcon);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('nusoft-theme', next);
      updateThemeIcon(next, themeIcon);
    });
  }
}

function updateThemeIcon(theme, iconEl) {
  if (!iconEl) return;
  if (theme === 'dark') {
    iconEl.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="5"></circle>
        <line x1="12" y1="1" x2="12" y2="3"></line>
        <line x1="12" y1="21" x2="12" y2="23"></line>
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
        <line x1="1" y1="12" x2="3" y2="12"></line>
        <line x1="21" y1="12" x2="23" y2="12"></line>
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
      </svg>
    `;
  } else {
    iconEl.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
      </svg>
    `;
  }
}

/* -------------------------------------------------------------
   2. Navbar Scroll Glass Effect
   ------------------------------------------------------------- */
function initNavbarScroll() {
  const navbar = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 40) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });
}

/* -------------------------------------------------------------
   2.5 Mobile Hamburger Navigation
   ------------------------------------------------------------- */
function initMobileNav() {
  const toggle = document.querySelector('.nav-toggle');
  const links = document.getElementById('navLinks');
  if (!toggle || !links) return;

  const closeMenu = () => {
    toggle.setAttribute('aria-expanded', 'false');
    links.classList.remove('open');
  };

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    links.classList.toggle('open', !expanded);
  });

  links.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', closeMenu);
  });

  document.addEventListener('click', (e) => {
    if (links.classList.contains('open') && !links.contains(e.target) && !toggle.contains(e.target)) {
      closeMenu();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && links.classList.contains('open')) {
      closeMenu();
      toggle.focus();
    }
  });
}

/* -------------------------------------------------------------
   3. NuShift Real-time Staffing Simulator
   ------------------------------------------------------------- */
function initSimulator() {
  const s0 = document.getElementById('simAge0');
  const s1 = document.getElementById('simAge1');
  const s3 = document.getElementById('simAge3');
  const s4 = document.getElementById('simAge4');
  const ruleSelect = document.getElementById('simRuleSelect');

  const v0 = document.getElementById('valAge0');
  const v1 = document.getElementById('valAge1');
  const v3 = document.getElementById('valAge3');
  const v4 = document.getElementById('valAge4');

  const totalStaffEl = document.getElementById('simTotalStaff');
  const totalChildrenEl = document.getElementById('simTotalChildren');

  const b0 = document.getElementById('bdAge0');
  const b1 = document.getElementById('bdAge1');
  const b3 = document.getElementById('bdAge3');
  const b4 = document.getElementById('bdAge4');

  if (!s0 || !s1 || !s3 || !s4) return;

  function recalculate() {
    const n0 = parseInt(s0.value, 10);
    const n1 = parseInt(s1.value, 10);
    const n3 = parseInt(s3.value, 10);
    const n4 = parseInt(s4.value, 10);

    v0.textContent = `${n0}名`;
    v1.textContent = `${n1}名`;
    v3.textContent = `${n3}名`;
    v4.textContent = `${n4}名`;

    const rule = ruleSelect.value;
    let r3 = 20;
    let r4 = 30;

    if (rule === 'tokyo') {
      r3 = 15;
      r4 = 25;
    } else if (rule === 'handy') {
      r3 = 15;
      r4 = 20;
    }

    // 厚労省配置基準端数計算 (法的には各クラス小数点を足してから切り上げる自治体とクラス別切り上げがあるが、概算標準算出)
    // 0歳: 3:1, 1・2歳: 6:1, 3歳: 20:1(15:1), 4・5歳: 30:1(25:1)
    const req0 = n0 > 0 ? Math.ceil(n0 / 3) : 0;
    const req1 = n1 > 0 ? Math.ceil(n1 / 6) : 0;
    const req3 = n3 > 0 ? Math.ceil(n3 / r3) : 0;
    const req4 = n4 > 0 ? Math.ceil(n4 / r4) : 0;

    let totalStaff = req0 + req1 + req3 + req4;
    // 乳幼児保育の最低配置基準（開所時は最低保育士2名必須）
    if (totalStaff < 2 && (n0 + n1 + n3 + n4) > 0) {
      totalStaff = 2;
    }

    totalStaffEl.textContent = totalStaff;
    totalChildrenEl.textContent = n0 + n1 + n3 + n4;

    b0.textContent = `${req0}名 (3:1)`;
    b1.textContent = `${req1}名 (6:1)`;
    b3.textContent = `${req3}名 (${r3}:1)`;
    b4.textContent = `${req4}名 (${r4}:1)`;
  }

  [s0, s1, s3, s4].forEach(slider => slider.addEventListener('input', recalculate));
  ruleSelect.addEventListener('change', recalculate);

  recalculate();
}

/* -------------------------------------------------------------
   4. Feature Showcase Tabs (ARIA & Keyboard Support)
   ------------------------------------------------------------- */
function initFeatureTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach((btn, index) => {
    btn.addEventListener('click', () => {
      const target = btn.getAttribute('data-tab');

      tabBtns.forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
        b.setAttribute('tabindex', '-1');
      });
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      btn.setAttribute('tabindex', '0');
      const activeContent = document.getElementById(`tab-${target}`);
      if (activeContent) {
        activeContent.classList.add('active');
      }
    });

    btn.addEventListener('keydown', (e) => {
      let nextIndex = null;
      if (e.key === 'ArrowRight') nextIndex = (index + 1) % tabBtns.length;
      if (e.key === 'ArrowLeft') nextIndex = (index - 1 + tabBtns.length) % tabBtns.length;
      if (e.key === 'Home') nextIndex = 0;
      if (e.key === 'End') nextIndex = tabBtns.length - 1;
      if (nextIndex !== null) {
        e.preventDefault();
        tabBtns[nextIndex].focus();
        tabBtns[nextIndex].click();
      }
    });
  });
}

/* -------------------------------------------------------------
   5. FAQ Accordion (ARIA Support)
   ------------------------------------------------------------- */
function initFaqAccordion() {
  const faqItems = document.querySelectorAll('.faq-item');

  faqItems.forEach(item => {
    const question = item.querySelector('.faq-question');
    const answer = item.querySelector('.faq-answer');
    const icon = item.querySelector('.faq-icon');

    question.setAttribute('role', 'button');
    question.setAttribute('tabindex', '0');
    question.setAttribute('aria-expanded', item.classList.contains('active') ? 'true' : 'false');
    if (icon) icon.setAttribute('aria-hidden', 'true');

    const toggle = () => {
      const isActive = item.classList.contains('active');

      // 他を閉じる
      faqItems.forEach(other => {
        other.classList.remove('active');
        const ans = other.querySelector('.faq-answer');
        const q = other.querySelector('.faq-question');
        if (ans) ans.style.maxHeight = null;
        if (q) q.setAttribute('aria-expanded', 'false');
      });

      if (!isActive) {
        item.classList.add('active');
        answer.style.maxHeight = answer.scrollHeight + 30 + 'px';
        question.setAttribute('aria-expanded', 'true');
      }
    };

    question.addEventListener('click', toggle);
    question.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    });
  });
}

/* -------------------------------------------------------------
   6. Demo & Contact Modal (Focus Management & Escape)
   ------------------------------------------------------------- */
function initModal() {
  const openBtns = document.querySelectorAll('.open-modal-btn');
  const modal = document.getElementById('demoModal');
  const closeBtn = document.getElementById('closeModalBtn');
  const form = document.getElementById('demoForm');

  if (!modal) return;

  const openModal = (trigger) => {
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const firstInput = modal.querySelector('input, select, button');
    if (firstInput) firstInput.focus();
    modal._lastTrigger = trigger || null;
  };

  const closeModal = () => {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (modal._lastTrigger) modal._lastTrigger.focus();
  };

  openBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      openModal(btn);
    });
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', closeModal);
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeModal();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      closeModal();
    }
  });

  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      const originalText = submitBtn.textContent;
      submitBtn.disabled = true;
      submitBtn.textContent = '送信中...';

      setTimeout(() => {
        form.innerHTML = `
          <div style="text-align: center; padding: 20px 0;">
            <div style="font-size: 3rem; margin-bottom: 12px;">🎉</div>
            <h3 style="font-size: 1.5rem; margin-bottom: 8px;">お申し込みを受け付けました</h3>
            <p style="color: var(--text-secondary); font-size: 0.95rem; margin-bottom: 24px;">
              ご登録いただいたメールアドレス宛に、デモ環境のログイン情報をお送りいたします。
            </p>
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('demoModal').classList.remove('open'); location.reload();">閉じる</button>
          </div>
        `;
      }, 1000);
    });
  }
}

/* -------------------------------------------------------------
   7. Scroll Reveal Animation (IntersectionObserver)
   ------------------------------------------------------------- */
function initScrollReveal() {
  const targets = document.querySelectorAll('.reveal');
  if (!targets.length) return;

  if (!('IntersectionObserver' in window)) {
    targets.forEach(el => el.classList.add('is-visible'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  targets.forEach(el => observer.observe(el));
}

/* -------------------------------------------------------------
   8. Animated Stat Counters
   ------------------------------------------------------------- */
function initStatCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const formatValue = (value, el) => {
    const useComma = el.getAttribute('data-format') === 'comma';
    const num = useComma ? value.toLocaleString('en-US') : String(value);
    return (el.getAttribute('data-prefix') || '') + num + (el.getAttribute('data-suffix') || '');
  };

  const animate = (el) => {
    const target = parseInt(el.getAttribute('data-count'), 10);
    if (prefersReducedMotion || isNaN(target) || target === 0) {
      el.textContent = formatValue(target, el);
      return;
    }
    const duration = 1400;
    const startTime = performance.now();
    const step = (now) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = formatValue(Math.round(target * eased), el);
      if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  if (!('IntersectionObserver' in window)) {
    counters.forEach(animate);
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animate(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.4 });

  counters.forEach(el => observer.observe(el));
}

/* -------------------------------------------------------------
   9. Scroll Spy (Active Nav Highlight)
   ------------------------------------------------------------- */
function initScrollSpy() {
  const sections = document.querySelectorAll('main section[id]');
  const navLinks = document.querySelectorAll('.nav-link[href^="#"]');
  if (!sections.length || !navLinks.length) return;

  const setActive = (id) => {
    navLinks.forEach(link => {
      link.classList.toggle('active', link.getAttribute('href') === `#${id}`);
    });
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        setActive(entry.target.id);
      }
    });
  }, { rootMargin: '-40% 0px -55% 0px' });

  sections.forEach(section => observer.observe(section));
}

/* -------------------------------------------------------------
   10. Hero Interactive Dashboard Demo (NuShift Live Preview)
   ------------------------------------------------------------- */
function initHeroDemo() {
  const recomputeBtn = document.getElementById('heroRecomputeBtn');
  const pinToggleBtn = document.getElementById('heroPinToggleBtn');
  const gapSimBtn = document.getElementById('heroGapSimBtn');
  const autoFixBtn = document.getElementById('heroAutoFixBtn');
  const gapAlertBox = document.getElementById('heroGapAlertBox');
  const pinCell = document.getElementById('heroPinCell');

  const statusPill = document.getElementById('mockupStatusPill');
  const compliancePill = document.getElementById('mockupCompliancePill');
  const violationText = document.getElementById('mockupViolationText');
  const pinCountText = document.getElementById('mockupPinCount');
  const gapStatusText = document.getElementById('mockupGapStatus');
  const miniGrid = document.getElementById('heroMiniGrid');

  if (!recomputeBtn || !statusPill) return;

  let isPinned = true;
  let hasGapAlert = false;
  let isSolving = false;

  // 1. Recompute Simulation (CBC Solver Pulse)
  const triggerRecompute = (callback) => {
    if (isSolving) return;
    isSolving = true;
    statusPill.textContent = '● 最適化求解中 (CBCソルバー)...';
    statusPill.className = 'status-pill pinned';

    // Animate grid cells
    if (miniGrid) {
      const cells = miniGrid.querySelectorAll('.grid-cell:not(:first-child)');
      cells.forEach(c => c.classList.add('calc-pulse'));
      setTimeout(() => cells.forEach(c => c.classList.remove('calc-pulse')), 600);
    }

    setTimeout(() => {
      isSolving = false;
      statusPill.textContent = '● 最適化完了 (CBC求解 18.2秒)';
      statusPill.className = 'status-pill success';
      if (callback) callback();
    }, 700);
  };

  recomputeBtn.addEventListener('click', () => {
    triggerRecompute();
  });

  // 2. Toggle Pin Status
  const togglePin = () => {
    isPinned = !isPinned;
    if (isPinned) {
      pinCell.textContent = '早番 📌';
      pinCell.classList.add('highlight');
      pinCountText.textContent = '12コマ固定中';
      pinToggleBtn.classList.add('active');
    } else {
      pinCell.textContent = '早番';
      pinCell.classList.remove('highlight');
      pinCountText.textContent = '11コマ固定中';
      pinToggleBtn.classList.remove('active');
    }
  };

  pinToggleBtn.addEventListener('click', () => {
    togglePin();
    triggerRecompute();
  });

  if (pinCell) {
    pinCell.addEventListener('click', () => {
      togglePin();
      triggerRecompute();
    });
  }

  // 3. Gap Alert Simulation (Late pickup change)
  const toggleGapAlert = (forceAlert) => {
    hasGapAlert = typeof forceAlert === 'boolean' ? forceAlert : !hasGapAlert;

    if (hasGapAlert) {
      gapAlertBox.classList.add('visible');
      gapSimBtn.classList.add('active');
      compliancePill.textContent = '配置充足率 88% ⚠️';
      compliancePill.className = 'status-pill';
      compliancePill.style.background = 'rgba(244, 63, 94, 0.2)';
      compliancePill.style.color = '#ff859b';
      gapStatusText.textContent = '遅番 1名不足 (17:30-18:30)';
      gapStatusText.style.color = 'var(--accent-rose)';
      violationText.textContent = '配置割れ警告あり';
      violationText.style.color = 'var(--accent-rose)';
    } else {
      gapAlertBox.classList.remove('visible');
      gapSimBtn.classList.remove('active');
      compliancePill.textContent = '配置充足率 100%';
      compliancePill.className = 'status-pill success';
      compliancePill.style.background = '';
      compliancePill.style.color = '';
      gapStatusText.textContent = '過不足なし (正常)';
      gapStatusText.style.color = 'var(--accent-emerald)';
      violationText.textContent = '0件 (パス)';
      violationText.style.color = 'var(--accent-emerald)';
    }
  };

  gapSimBtn.addEventListener('click', () => {
    toggleGapAlert();
  });

  if (autoFixBtn) {
    autoFixBtn.addEventListener('click', () => {
      triggerRecompute(() => {
        toggleGapAlert(false);
      });
    });
  }
}

/* -------------------------------------------------------------
   11. ROI & Cost Benefit Calculator
   ------------------------------------------------------------- */
function initRoiSimulator() {
  const btnStaff = document.getElementById('btnSimStaff');
  const btnRoi = document.getElementById('btnSimRoi');
  const panelStaff = document.getElementById('panelSimStaff');
  const panelRoi = document.getElementById('panelSimRoi');

  const sChildren = document.getElementById('roiChildren');
  const sStaff = document.getElementById('roiStaff');
  const sHours = document.getElementById('roiHours');

  const vChildren = document.getElementById('valRoiChildren');
  const vStaff = document.getElementById('valRoiStaff');
  const vHours = document.getElementById('valRoiHours');

  const outHours = document.getElementById('roiReducedHours');
  const outYen = document.getElementById('roiSavedYen');
  const outRoi = document.getElementById('roiMultiple');

  if (!btnStaff || !btnRoi || !panelStaff || !panelRoi) return;

  // Mode Switch
  btnStaff.addEventListener('click', () => {
    btnStaff.classList.add('active');
    btnRoi.classList.remove('active');
    panelStaff.classList.add('active');
    panelRoi.classList.remove('active');
  });

  btnRoi.addEventListener('click', () => {
    btnRoi.classList.add('active');
    btnStaff.classList.remove('active');
    panelRoi.classList.add('active');
    panelStaff.classList.remove('active');
  });

  if (!sChildren || !sStaff || !sHours) return;

  const calculateRoi = () => {
    const children = parseInt(sChildren.value, 10);
    const staff = parseInt(sStaff.value, 10);
    const hours = parseInt(sHours.value, 10);

    vChildren.textContent = `${children}名`;
    vStaff.textContent = `${staff}名`;
    vHours.textContent = `${hours}時間/月`;

    // 業務削減比率 (シフト作成・登降園集計・全銀出力で工数の約85%を削減)
    const monthlySavedHours = Math.round(hours * 0.85);
    const yearlySavedHours = monthlySavedHours * 12;

    // 時給 ¥2,500 換算 (保育士・主任・園長平均人件費)
    const hourlyCost = 2500;
    const yearlySavingsYen = yearlySavedHours * hourlyCost;

    // クラウド版年間費用 (¥19,800 * 12 = ¥237,600)
    const yearlySystemCost = 19800 * 12;
    const roiPercentage = Math.round((yearlySavingsYen / yearlySystemCost) * 100);

    outHours.innerHTML = `${yearlySavedHours.toLocaleString()}<span class="roi-stat-unit">時間</span>`;
    outYen.textContent = `¥${yearlySavingsYen.toLocaleString()}`;
    outRoi.innerHTML = `${roiPercentage}<span class="roi-stat-unit">%</span>`;
  };

  [sChildren, sStaff, sHours].forEach(el => el.addEventListener('input', calculateRoi));
  calculateRoi();
}

/* -------------------------------------------------------------
   12. Floating Sticky CTA Bar (Scroll Observer)
   ------------------------------------------------------------- */
function initFloatingCta() {
  const bar = document.getElementById('floatingCtaBar');
  if (!bar) return;

  window.addEventListener('scroll', () => {
    if (window.scrollY > 380) {
      bar.classList.add('visible');
    } else {
      bar.classList.remove('visible');
    }
  }, { passive: true });
}
