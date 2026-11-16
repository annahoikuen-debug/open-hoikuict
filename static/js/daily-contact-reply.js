(() => {
  const form = document.getElementById('daily-reply-form');
  if (!form) return;
  const fields = [...form.elements].filter(e => e.name.startsWith('reply_'));
  const snapshot = () => JSON.stringify(fields.map(e => [e.name, e.value]));
  let saved = snapshot(), pendingUrl = '', busy = false;
  const leave = document.getElementById('reply-leave-dialog');
  const publish = document.getElementById('reply-publish-dialog');
  const error = document.getElementById('reply-save-error');
  const conflictBanner = document.getElementById('reply-conflict-banner');
  const conflictMessage = document.getElementById('reply-conflict-message');
  const conflictCopyBtn = document.getElementById('reply-conflict-copy-btn');
  const conflictDismiss = document.getElementById('reply-conflict-dismiss');
  const autoSaveDot = document.getElementById('reply-autosave-dot');
  const autoSaveText = document.getElementById('reply-autosave-text');

  let autoSaveTimer = null;
  const AUTO_SAVE_DELAY_MS = 30000; // 30秒

  const setAutoSaveStatus = (type, message) => {
    if (!autoSaveDot || !autoSaveText) return;
    if (type === 'editing') {
      autoSaveDot.className = 'inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse';
      autoSaveText.textContent = message || '編集中...（30秒後に自動保存）';
      autoSaveText.className = 'text-amber-700 font-medium';
    } else if (type === 'saving') {
      autoSaveDot.className = 'inline-block w-2 h-2 rounded-full bg-indigo-400 animate-pulse';
      autoSaveText.textContent = message || '自動保存中...';
      autoSaveText.className = 'text-indigo-600 font-medium';
    } else if (type === 'saved') {
      autoSaveDot.className = 'inline-block w-2 h-2 rounded-full bg-emerald-500';
      autoSaveText.textContent = message;
      autoSaveText.className = 'text-emerald-700 font-medium';
    } else if (type === 'conflict') {
      autoSaveDot.className = 'inline-block w-2 h-2 rounded-full bg-rose-500';
      autoSaveText.textContent = '競合発生のため自動保存停止';
      autoSaveText.className = 'text-rose-700 font-semibold';
    } else {
      autoSaveDot.className = 'inline-block w-2 h-2 rounded-full bg-slate-300';
      autoSaveText.textContent = '自動保存有効 (30秒間隔)';
      autoSaveText.className = 'text-slate-400';
    }
  };

  const dirty = () => saved !== snapshot();

  const scheduleAutoSave = () => {
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    if (!dirty() || busy) return;
    setAutoSaveStatus('editing');
    autoSaveTimer = setTimeout(async () => {
      if (dirty() && !busy) {
        setAutoSaveStatus('saving');
        await save('draft', null, true);
      }
    }, AUTO_SAVE_DELAY_MS);
  };

  const update = () => {
    document.getElementById('reply-edit-state').textContent = dirty() ? '未送信・編集中（変更はまだ保存されていません）' : '';
    document.getElementById('reply-reset').hidden = !dirty();
    form.querySelectorAll('[data-choice-group]').forEach(group => group.querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-pressed', String(form.elements[group.dataset.choiceGroup].value === button.dataset.replyChoice));
    }));
    const [whole = '', fraction = ''] = form.elements.reply_temperature.value.split('.');
    form.querySelectorAll('[data-temperature-whole]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.temperatureWhole === whole)));
    form.querySelectorAll('[data-temperature-fraction]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.temperatureFraction === fraction)));

    if (dirty()) {
      scheduleAutoSave();
    } else {
      if (autoSaveTimer) clearTimeout(autoSaveTimer);
    }
  };

  form.querySelectorAll('[data-choice-group]').forEach(group => {
    group.hidden = false;
    form.elements[group.dataset.choiceGroup].hidden = true;
    group.addEventListener('click', event => {
      const button = event.target.closest('[data-reply-choice]');
      if (!button) return;
      form.elements[group.dataset.choiceGroup].value = button.dataset.replyChoice;
      update();
    });
  });
  form.querySelector('.reply-temperature').hidden = false;
  form.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const input = form.elements.reply_temperature;
    const [whole = '', fraction = ''] = input.value.split('.');
    if (button.hasAttribute('data-temperature-whole')) input.value = `${button.dataset.temperatureWhole}.${fraction}`;
    if (button.hasAttribute('data-temperature-fraction')) input.value = `${whole}.${button.dataset.temperatureFraction}`;
    if (button.hasAttribute('data-temperature-clear')) input.value = '';
    update();
  });
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  document.getElementById('reply-reset').addEventListener('click', () => {
    for (const [name, value] of JSON.parse(saved)) form.elements[name].value = value;
    error.textContent = '';
    setAutoSaveStatus('idle');
    update();
  });

  // P4-4: 前日の返信をコピー
  const copyPrevBtn = document.getElementById('copy-previous-reply-btn');
  const prevJsonEl = document.getElementById('previous-reply-json');
  if (copyPrevBtn && prevJsonEl) {
    copyPrevBtn.addEventListener('click', () => {
      try {
        const prevData = JSON.parse(prevJsonEl.textContent);
        if (!prevData) return;
        const vals = prevData.values || {};
        for (const [key, val] of Object.entries(vals)) {
          const el = form.elements['reply_' + key];
          if (el) el.value = val || '';
        }
        if (form.elements.reply_message) {
          form.elements.reply_message.value = prevData.message || '';
        }
        update();
        document.getElementById('reply-edit-state').textContent = `前日（${prevData.date_label}分）の内容をコピーしました。`;
      } catch (err) {
        console.error('前日コピー失敗:', err);
      }
    });
  }

  // 競合バナーのボタン
  if (conflictCopyBtn) {
    conflictCopyBtn.addEventListener('click', () => {
      const msg = form.elements.reply_message?.value || '';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(msg).then(() => {
          alert('入力中の連絡メモをクリップボードにコピーしました！\n画面を再読み込み後、貼り付けてください。');
        });
      } else {
        alert('クリップボードAPI非対応環境です。手動でコピーしてください。');
      }
    });
  }
  if (conflictDismiss && conflictBanner) {
    conflictDismiss.addEventListener('click', () => {
      conflictBanner.classList.add('hidden');
    });
  }

  const save = async (action, dialog = null, isAutoSave = false) => {
    if (busy || !form.reportValidity()) return false;
    const data = new FormData(form);
    data.set('action', action);
    const submitted = snapshot();
    busy = true;
    const buttons = [...form.querySelectorAll('button'), ...document.querySelectorAll('.reply-dialog button')];
    if (!isAutoSave) {
      buttons.forEach(button => button.disabled = true);
    }
    error.textContent = '';
    if (dialog) dialog.querySelector('[data-dialog-error]').textContent = '';
    try {
      const response = await fetch(form.getAttribute('action'), {
        method: 'POST',
        body: data,
        headers: {
          'X-Reply-Request': '1',
          'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
        }
      });

      if (!response.headers.get('content-type')?.includes('application/json') || response.redirected) {
        throw new Error('保存できませんでした。入力は残っています。ログイン状態を確認してください。');
      }
      const result = await response.json();

      if (response.status === 409) {
        // P4-2: 楽観ロック競合発生
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        setAutoSaveStatus('conflict');
        if (conflictBanner) {
          conflictBanner.classList.remove('hidden');
          if (conflictMessage && result.detail) {
            conflictMessage.textContent = result.detail;
          }
        }
        throw new Error(result.detail || '他の職員によって返信が更新されました。');
      }

      if (!response.ok) {
        throw new Error(result.detail || '保存できませんでした。もう一度お試しください。');
      }

      saved = submitted;
      form.elements.revision.value = result.revision;
      const state = document.getElementById('reply-state');
      if (state) state.textContent = result.status;
      if (conflictBanner) conflictBanner.classList.add('hidden');

      const now = new Date();
      const timeStr = now.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      if (isAutoSave) {
        setAutoSaveStatus('saved', `${timeStr} に自動保存しました`);
      } else {
        setAutoSaveStatus('saved', `${timeStr} に下書きを保存しました`);
      }

      update();
      if (!dirty()) document.getElementById('reply-edit-state').textContent = result.notice;
      return true;
    } catch (reason) {
      error.textContent = reason.message;
      if (dialog) dialog.querySelector('[data-dialog-error]').textContent = reason.message;
      return false;
    } finally {
      busy = false;
      if (!isAutoSave) {
        buttons.forEach(button => button.disabled = false);
      }
    }
  };

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (event.submitter?.value !== 'publish') {
      save('draft');
      return;
    }
    const preview = document.getElementById('reply-publish-preview');
    preview.replaceChildren();
    fields.forEach(field => {
      const term = document.createElement('dt'), value = document.createElement('dd');
      term.textContent = form.querySelector(`label[for="${field.id}"]`)?.textContent || field.name;
      value.textContent = field.value || '未入力';
      preview.append(term, value);
    });
    publish.querySelector('[data-dialog-error]').textContent = '';
    publish.showModal();
  });

  publish.querySelector('[data-publish=back]').addEventListener('click', () => publish.close());
  publish.querySelector('[data-publish=confirm]').addEventListener('click', async () => {
    if (await save('publish', publish)) publish.close();
  });

  const navigate = url => {
    if (!dirty()) { window.location.assign(url); return; }
    pendingUrl = url;
    leave.querySelector('[data-dialog-error]').textContent = '';
    leave.showModal();
  };

  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0 || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
    if (!dirty() || anchor.getAttribute('href').startsWith('#')) return;
    event.preventDefault();
    navigate(anchor.href);
  });

  document.querySelector('.reply-date-nav form')?.addEventListener('submit', event => {
    event.preventDefault();
    const target = new URL(window.location.href);
    target.search = new URLSearchParams(new FormData(event.target)).toString();
    navigate(target.href);
  });

  leave.querySelectorAll('[data-leave]').forEach(button => button.addEventListener('click', async () => {
    if (button.dataset.leave === 'stay') { leave.close(); return; }
    if (button.dataset.leave === 'save' && !(await save('draft', leave))) return;
    saved = snapshot();
    window.location.assign(pendingUrl);
  }));

  [leave, publish].forEach(dialog => dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); }));
  window.addEventListener('beforeunload', event => { if (dirty() || busy) { event.preventDefault(); event.returnValue = ''; } });
  update();
})();
