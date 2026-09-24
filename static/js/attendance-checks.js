let pendingVerification = null;
document.addEventListener('htmx:afterSwap', () => {
  const day = document.getElementById('attendance-checks-board')?.dataset.targetDate;
  const link = document.querySelector('[data-roster-link]');
  if (day && link) link.href = `/attendance-checks/roster?date=${encodeURIComponent(day)}`;
});
function openVerificationDialog(button) {
  pendingVerification = button.form;
  const dialog = document.getElementById('verification-dialog');
  document.getElementById('verification-confirm').reset();
  document.getElementById('verification-title').textContent = `${button.dataset.childName}：${button.textContent.trim()}`;
  const reason = document.getElementById('verification-reason');
  reason.required = button.dataset.requiresReason === 'true';
  document.getElementById('verification-required').textContent = reason.required ? '（必須）' : '（初回確認は任意）';
  document.getElementById('verification-notify-label').hidden = button.dataset.statusKey !== 'unknown';
  document.getElementById('verification-error').textContent = '';
  dialog.showModal();
  reason.focus();
}
document.getElementById('verification-confirm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!pendingVerification) return;
  const submit = event.submitter;
  const data = new FormData(pendingVerification);
  data.set('reason', document.getElementById('verification-reason').value.trim());
  data.set('notify_parent', String(document.getElementById('verification-notify').checked));
  submit.disabled = true;
  try {
    const response = await fetch(pendingVerification.action, {method: 'POST', body: data, headers: {
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
    window.scrollTo(0, scroll);
  } catch (error) { document.getElementById('verification-error').textContent = error.message; }
  finally { submit.disabled = false; }
});
