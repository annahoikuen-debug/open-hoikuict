let pendingVerification = null;
let verificationSaving = false;
let audioCtx = null;

function getAudioContext() {
  try {
    if (!audioCtx && (window.AudioContext || window.webkitAudioContext)) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  } catch (e) {
    return null;
  }
}

function playTone(freq, duration, delay = 0, type = 'sine', volume = 0.15) {
  const ctx = getAudioContext();
  if (!ctx) return;
  try {
    const startTime = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, startTime);
    gain.gain.setValueAtTime(volume, startTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(startTime);
    osc.stop(startTime + duration);
  } catch (e) {
    // Audio playback is non-blocking and safe to fail silently
  }
}

function playCheckBeep() {
  // G5 (783.99Hz) - やさしい単音タップ音 (100ms)
  playTone(783.99, 0.1, 0, 'sine', 0.12);
}

function playAllCompleteFanfare() {
  // C5 (523Hz) -> E5 (659Hz) -> G5 (784Hz) - 点呼完了アルペジオ♪
  playTone(523.25, 0.09, 0, 'triangle', 0.15);
  playTone(659.25, 0.09, 0.08, 'triangle', 0.15);
  playTone(783.99, 0.22, 0.16, 'sine', 0.18);
}

document.addEventListener('htmx:afterSwap', () => {
  const day = document.getElementById('attendance-checks-board')?.dataset.targetDate;
  const link = document.querySelector('[data-roster-link]');
  if (day && link) link.href = `/attendance-checks/roster?date=${encodeURIComponent(day)}`;
});
function openVerificationDialog(button) {
  if (verificationSaving || button.getAttribute('aria-pressed') === 'true') return;
  if (button.dataset.requiresReason !== 'true') {
    saveVerification(button.form, '', false, false);
    return;
  }
  pendingVerification = button.form;
  const dialog = document.getElementById('verification-dialog');
  document.getElementById('verification-confirm').reset();
  document.getElementById('verification-title').textContent = `${button.dataset.childName}：${button.textContent.trim()}`;
  const reason = document.getElementById('verification-reason');
  reason.required = true;
  document.getElementById('verification-required').textContent = '（必須）';
  document.getElementById('verification-notify-label').hidden = button.dataset.statusKey !== 'unknown';
  document.getElementById('verification-error').textContent = '';
  dialog.showModal();
  reason.focus();
}
async function saveVerification(form, reason, notify, fromDialog) {
  if (verificationSaving) return;
  verificationSaving = true;
  const currentBoard = document.getElementById('attendance-checks-board');
  const prevUnknownCount = parseInt(currentBoard?.dataset.unknownCount || '0', 10);
  const errorBox = document.getElementById(fromDialog ? 'verification-error' : 'verification-inline-error');
  errorBox.textContent = '';
  const controls = document.querySelectorAll('[data-verification-form] button, #verification-confirm button, .compact-toolbar button');
  controls.forEach(button => { button.disabled = true; });
  const data = new FormData(form);
  data.set('reason', reason);
  data.set('notify_parent', String(notify));
  try {
    const response = await fetch(form.action, {method: 'POST', body: data, headers: {
      'HX-Request': 'true', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
    }});
    if (!response.ok || response.redirected) {
      let message = '保存できませんでした。入力は残っています。ログイン状態を確認して、もう一度お試しください。';
      if (response.headers.get('content-type')?.includes('application/json')) message = (await response.json()).detail || message;
      throw new Error(message);
    }
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const board = parsed.getElementById('attendance-checks-board');
    if (!board) throw new Error('保存結果を確認できませんでした。画面を再読み込みしてください。');
    const scroll = window.scrollY;
    document.getElementById('attendance-checks-board').replaceWith(board);
    window.htmx?.process(board);
    document.getElementById('verification-dialog').close();
    pendingVerification = null;
    window.scrollTo(0, scroll);

    // 点呼フィードバック音の再生
    const newUnknownCount = parseInt(board.dataset.unknownCount || '0', 10);
    const newAlarmCount = parseInt(board.dataset.alarmCount || '0', 10);
    if (prevUnknownCount > 0 && newUnknownCount === 0 && newAlarmCount === 0) {
      playAllCompleteFanfare();
    } else {
      playCheckBeep();
    }
  } catch (error) { errorBox.textContent = error.message; }
  finally {
    verificationSaving = false;
    controls.forEach(button => { button.disabled = false; });
  }
}
document.getElementById('verification-confirm')?.addEventListener('submit', event => {
  event.preventDefault();
  if (!pendingVerification) return;
  saveVerification(pendingVerification, document.getElementById('verification-reason').value.trim(), document.getElementById('verification-notify').checked, true);
});
document.querySelectorAll('[data-reason-preset]').forEach(button => button.addEventListener('click', () => {
  const reason = document.getElementById('verification-reason');
  reason.value = button.dataset.reasonPreset;
  reason.focus();
}));
document.getElementById('verification-dialog')?.addEventListener('cancel', event => {
  if (verificationSaving) event.preventDefault();
});
