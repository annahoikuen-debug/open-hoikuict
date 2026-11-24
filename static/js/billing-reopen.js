(() => {
  'use strict';
  const dialog = document.getElementById('billing-reopen-dialog');
  const form = document.getElementById('billing-reopen-form');
  const dirty = new Set();
  document.querySelectorAll('form[data-billing-edit]').forEach(edit => {
    edit.addEventListener('input', () => dirty.add(edit));
    edit.addEventListener('change', () => dirty.add(edit));
  });
  const allowLeave = () => !dirty.size || window.confirm('まだ保存していない入力があります。入力を破棄して移動しますか？');
  const submitButton = () => form.querySelector('button[type=submit]');
  const templateBoxes = () => Array.from(form.querySelectorAll('input[name="reason_tpl"]'));

  function open(data) {
    if (!dialog || !/^\d+$/.test(String(data.id))) return;
    const approveMode = Boolean(data.approve);
    form.action = approveMode
      ? `/billing/zengin/exports/${data.id}/reopen-approve-ui`
      : `/billing/zengin/exports/${data.id}/cancel-ui`;
    document.getElementById('billing-reopen-summary').textContent =
      `${data.month} ／ 出力 #${data.id} ／ ${data.count}件 ／ ${Number(data.amount).toLocaleString('ja-JP')}円`;

    const levelEl = document.getElementById('billing-reopen-level');
    const deltaEl = document.getElementById('billing-reopen-delta');
    const deltaText = document.getElementById('billing-reopen-delta-text');
    const requestSummary = document.getElementById('billing-reopen-request-summary');
    const reasonFieldset = document.getElementById('billing-reopen-reason-fieldset');

    templateBoxes().forEach(box => { box.checked = false; });
    form.elements.reason.value = data.reason || '';
    form.elements.confirmed_unsubmitted.checked = Boolean(data.checked);

    if (approveMode) {
      const payload = data.payload || {};
      const templates = payload.reason_templates || [];
      const free = payload.reason_free || '';
      levelEl.hidden = false;
      levelEl.textContent = 'L1（差額あり）の解除申請を承認します。';
      deltaEl.hidden = false;
      const delta = Number(payload.delta_amount || 0);
      deltaText.textContent = ` ${delta ? (delta > 0 ? '+' : '') + delta.toLocaleString('ja-JP') + '円' : '差額なし'}（推定 ${payload.estimated_count ?? data.count}件・${Number(payload.estimated_amount ?? data.amount).toLocaleString('ja-JP')}円）`;
      requestSummary.hidden = false;
      requestSummary.textContent = `申請者: ${data.requested_by || ''}${data.requested_at ? ' ／ 申請 ' + data.requested_at : ''} ／ 理由: ${templates.join('、')}${free ? (templates.length ? '／' : '') + free : ''}`;
      reasonFieldset.hidden = true;
      form.elements.reason.value = '';
    } else {
      requestSummary.hidden = true;
      reasonFieldset.hidden = false;
      const level = data.level || '';
      if (level === 'L1') {
        levelEl.hidden = false;
        levelEl.textContent = 'L1: 再計算で請求額が変わるため、管理者はそのまま実行・それ以外は園長の確認が必要です。';
      } else if (level === 'L0') {
        levelEl.hidden = false;
        levelEl.textContent = 'L0: 再計算の結果、請求金額に差異はありません。直接実行できます。';
      } else {
        levelEl.hidden = true;
        levelEl.textContent = '';
      }
      const hasDelta = data.delta !== undefined && data.delta !== null && data.delta !== '' && Number(data.delta) !== 0;
      deltaEl.hidden = !hasDelta;
      if (hasDelta) {
        const delta = Number(data.delta);
        deltaText.textContent = ` ${delta > 0 ? '+' : ''}${delta.toLocaleString('ja-JP')}円`;
      }
      (data.reason_templates || []).forEach(value => {
        const box = templateBoxes().find(candidate => candidate.value === value);
        if (box) box.checked = true;
      });
    }

    const error = document.getElementById('billing-reopen-error');
    error.textContent = data.error || ''; error.hidden = !data.error;
    submitButton().textContent = approveMode ? '承認して取消を実行' : (data.level === 'L1' ? 'この内容で園長に確認を依頼' : '取消して修正へ進む');
    submitButton().disabled = false;
    dialog.showModal();
  }
  document.querySelectorAll('[data-reopen-export]').forEach(button => button.addEventListener('click', () => open({
    id: button.dataset.reopenExport, month: button.dataset.reopenMonth,
    count: button.dataset.reopenCount, amount: button.dataset.reopenAmount,
    level: button.dataset.reopenLevel, delta: button.dataset.reopenDelta,
  })));
  document.querySelectorAll('[data-reopen-approve]').forEach(button => button.addEventListener('click', () => {
    let payload = {};
    try { payload = JSON.parse(button.dataset.reopenPayload || '{}'); } catch (_) { payload = {}; }
    open({
      id: button.dataset.reopenApprove, month: button.dataset.reopenMonth,
      count: button.dataset.reopenCount, amount: button.dataset.reopenAmount,
      requested_by: button.dataset.reopenRequestedBy, requested_at: button.dataset.reopenRequestedAt,
      payload, approve: true,
    });
  }));
  document.querySelector('[data-reopen-close]')?.addEventListener('click', () => dialog.close());
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.target === '_blank' || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = new URL(link.href, location.href);
    if (target.pathname === location.pathname && target.search === location.search && target.hash) return;
    if (!allowLeave()) event.preventDefault(); else dirty.clear();
  });
  document.addEventListener('submit', event => {
    const otherEdits = [...dirty].some(edit => edit !== event.target);
    if (otherEdits && !window.confirm('ほかの欄に保存していない入力があります。破棄してこの操作を続けますか？')) {
      event.preventDefault(); return;
    }
    if (event.target === form) {
      const approveMode = form.action.endsWith('/reopen-approve-ui');
      const reason = form.elements.reason;
      const hasTemplate = templateBoxes().some(box => box.checked);
      if (!approveMode && !hasTemplate && !reason.value.trim()) {
        event.preventDefault(); reason.setCustomValidity('取消理由を選択または入力してください。'); reason.reportValidity(); return;
      }
      if (approveMode && !form.elements.confirmed_unsubmitted.checked) {
        event.preventDefault();
        const error = document.getElementById('billing-reopen-error');
        error.textContent = '銀行へ提出・アップロードしていないことを確認してください。'; error.hidden = false;
        return;
      }
      submitButton().disabled = true;
    }
    dirty.clear();
  });
  form?.elements.reason.addEventListener('input', () => form.elements.reason.setCustomValidity(''));
  window.addEventListener('beforeunload', event => { if (dirty.size) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pageshow', () => { const submit = form ? submitButton() : null; if (submit) submit.disabled = false; });
  const initial = document.getElementById('billing-reopen-initial');
  if (initial) { const data = JSON.parse(initial.textContent); if (data) open(data); }
})();
