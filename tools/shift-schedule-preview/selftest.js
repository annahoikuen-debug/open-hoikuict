/* Temporary verification driver. Loads the built mock, exercises every
 * view x state combination plus the interactive flows, and reports any error.
 * Deleted after the check; not part of the preview the user opens.
 */
'use strict';

const REPORT = [];
function step(name, fn) {
  try {
    const detail = fn();
    REPORT.push({ name: name, ok: true, detail: detail == null ? '' : String(detail) });
  } catch (err) {
    REPORT.push({ name: name, ok: false, detail: (err && err.stack) || String(err) });
  }
}

window.addEventListener('load', function () {
  setTimeout(function () {
    /* ---- every view x state combination ---- */
    VIEWS.forEach(function (view) {
      MOCK_STATES[view].forEach(function (s) {
        step(view + '/' + s.id, function () {
          state.view = view;
          state.mock[view] = s.id;
          renderView();
          renderCurrent();
          const el = document.getElementById('view-' + view);
          const hiddenOthers = VIEWS.filter(function (v) {
            return v !== view && !document.getElementById('view-' + v).hidden;
          });
          if (hiddenOthers.length) { throw new Error('other views visible: ' + hiddenOthers); }
          return 'visible=' + !el.hidden + ' html=' + el.innerHTML.length;
        });
      });
    });

    /* ---- facility: valid save / invalid save / cancel / closed-day add+remove ---- */
    step('arrival/names-the-fallback', function () {
      /* 優先順位3〜5に落ちる園児がいるとき、补完元が名指しで出ること。 */
      state.view = 'arrival'; state.mock.arrival = 'default'; renderView(); renderCurrent();
      const body = document.getElementById('result-body');
      const warn = document.querySelectorAll('#arrival-body .badge--warn').length;
      const danger = document.querySelectorAll('#arrival-body .badge--danger').length;
      const rows = document.querySelectorAll('#arrival-body tr').length;
      if (!rows) { throw new Error('no child rows'); }
      if (!warn && !danger) { throw new Error('expected some children to fall back to level 4/5'); }
      if (document.getElementById('arrival-summary').textContent.indexOf('保育必要量区分') < 0) {
        throw new Error('summary must name the fallback level');
      }
      if (body) { /* no-op */ }
      return 'rows=' + rows + ' level4=' + warn + ' level5=' + danger;
    });
    step('arrival/filter-unset', function () {
      const sel = document.getElementById('arrival-filter');
      sel.value = 'unset';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      const rows = document.querySelectorAll('#arrival-body tr').length;
      const unset = state.children.filter(function (c) { return !c.planned; }).length;
      if (rows !== unset) { throw new Error('filter rows ' + rows + ' != unset ' + unset); }
      sel.value = 'all'; sel.dispatchEvent(new Event('change', { bubbles: true }));
      return 'unset rows=' + rows;
    });
    step('arrival/save-blocked-by-invalid', function () {
      state.mock.arrival = 'invalid'; renderCurrent();
      document.getElementById('arrival-save').click();
      const t = document.getElementById('arrival-msg').textContent;
      if (t.indexOf('保存できません') < 0) { throw new Error('expected a blocked save, got: ' + t); }
      return t.replace(/\s+/g, ' ').trim().slice(0, 100);
    });
    step('arrival/edit-default', function () {
      state.mock.arrival = 'default'; renderCurrent();
      const row = document.querySelector('#arrival-body tr[data-child="C-01"]');
      const input = row.querySelector('input[data-f="planned"]');
      input.value = '08:15';
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const after = state.children.filter(function (c) { return c.id === 'C-01'; })[0].planned;
      if (after !== '08:15') { throw new Error('edit not applied, got ' + after); }
      const level = document.querySelector('#arrival-body tr[data-child="C-01"] .badge').textContent;
      if (level.indexOf('園児ごとの既定値') < 0) { throw new Error('expected level 3 after edit, got ' + level); }
      return 'C-01 -> 08:15, 補完元=' + level;
    });
    step('arrival/override-add-remove', function () {
      const before = document.querySelectorAll('#override-body tr[data-ov]').length;
      document.getElementById('override-add').click();
      const added = document.querySelectorAll('#override-body tr[data-ov]').length;
      if (added !== before + 1) { throw new Error('override not added'); }
      document.querySelector('#override-body tr[data-ov="' + (added - 1) + '"] [data-remove-ov]').click();
      const removed = document.querySelectorAll('#override-body tr[data-ov]').length;
      if (removed !== before) { throw new Error('override not removed'); }
      return 'add/remove ok (' + before + ' -> ' + added + ' -> ' + removed + ')';
    });
    step('generate/button-disabled-with-reason', function () {
      /* CBC 不在などで生成できない状態では、ボタンが無効で理由が隣に出ること。 */
      ['empty', 'blocked', 'nocbc'].forEach(function (v) {
        state.view = 'generate'; state.mock.generate = v; renderView(); renderCurrent();
        const btn = document.getElementById('generate-run');
        if (!btn.disabled) { throw new Error(v + ': generate button must be disabled'); }
        const hint = document.getElementById('generate-blocked');
        if (hint.hidden || !hint.textContent.trim()) {
          throw new Error(v + ': disabled button must state a reason');
        }
      });
      /* failed は「解なし」なので再実行できなければならない。 */
      state.mock.generate = 'failed'; renderCurrent();
      if (document.getElementById('generate-run').disabled) {
        throw new Error('failed: must stay pressable to retry');
      }
      return 'empty/blocked/nocbc disabled with reason, failed pressable';
    });

    step('arrival/override-shows-on-its-day', function () {
      /* 確認する日を例外日の日に変えると、補完元が「その日の上書き」に変わること。 */
      state.view = 'arrival'; state.mock.arrival = 'default'; renderView(); renderCurrent();
      const day = document.getElementById('arrival-day');
      const readLevel = function (child) {
        const cell = document.querySelector('#arrival-body tr[data-child="' + child + '"] .badge');
        return cell ? cell.textContent : '(none)';
      };
      const before = readLevel('C-02');
      day.value = '2026-11-10';
      day.dispatchEvent(new Event('change', { bubbles: true }));
      const after = readLevel('C-02');
      if (before.indexOf('その日の上書き') >= 0) { throw new Error('C-02 should not start as an override'); }
      if (after.indexOf('その日の上書き') < 0) {
        throw new Error('C-02 on 2026-11-10 must resolve to その日の上書き, got ' + after);
      }
      day.value = '2026-11-04'; day.dispatchEvent(new Event('change', { bubbles: true }));
      if (readLevel('C-02').indexOf('その日の上書き') >= 0) { throw new Error('override leaked to another day'); }
      return 'C-02: ' + before + ' -> ' + after + ' -> back to default';
    });
    step('arrival/no-arrival-before-opening', function () {
      /* 保育必要量区分の開始時刻は施設の開園時刻以上。誤った赤表示がないこと。 */
      state.mock.arrival = 'default'; renderCurrent();
      const flagged = document.querySelectorAll('#arrival-body tr.is-missing').length;
      if (flagged) { throw new Error(flagged + ' children wrongly flagged as invalid'); }
      return 'no child flagged in the default state';
    });

    /* ---- facility: valid save / invalid save / cancel / closed-day add+remove ---- */
    step('facility/valid-save', function () {
      state.view = 'facility'; state.mock.facility = 'default'; renderView(); renderCurrent();
      const f = document.getElementById('facility-form');
      f.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      return document.getElementById('facility-msg').textContent.trim();
    });
    step('facility/invalid-save', function () {
      state.mock.facility = 'invalid'; renderCurrent();
      /* 状態切替した時点で、どの項目が悪いのか名指しで出ていること。 */
      const banner = document.getElementById('facility-state').textContent;
      if (banner.indexOf('閉園時刻は開園時刻より後にしてください') < 0) {
        throw new Error('state switch must name the offending field, got: ' + banner.trim());
      }
      const f = document.getElementById('facility-form');
      f.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      const t = document.getElementById('facility-msg').textContent;
      if (t.indexOf('保存できません') < 0) { throw new Error('expected a validation error, got: ' + t); }
      return 'banner names the field; ' + t.replace(/\s+/g, ' ').trim().slice(0, 60);
    });
    step('facility/empty-save', function () {
      state.mock.facility = 'empty'; renderCurrent();
      document.getElementById('facility-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      return document.getElementById('facility-msg').textContent.replace(/\s+/g, ' ').trim().slice(0, 120);
    });
    step('facility/cancel', function () {
      state.mock.facility = 'default'; renderCurrent();
      document.getElementById('facility-cancel').click();
      return document.getElementById('facility-msg').textContent.replace(/\s+/g, ' ').trim();
    });
    step('facility/closed-day-add-remove', function () {
      state.mock.facility = 'default'; renderCurrent();
      const before = document.querySelectorAll('#closed-day-list .chip').length;
      document.getElementById('closed-day-date').value = '2026-11-14';
      document.getElementById('closed-day-add').click();
      const added = document.querySelectorAll('#closed-day-list .chip').length;
      document.querySelector('[data-remove-day="' + (added - 1) + '"]').click();
      const removed = document.querySelectorAll('#closed-day-list .chip').length;
      if (!(added === before + 1 && removed === before)) {
        throw new Error('chip add/remove failed: ' + before + '/' + added + '/' + removed);
      }
      return before + ' -> ' + added + ' -> ' + removed;
    });

    /* ---- contracts: edit, save (blocked), reset, filter ---- */
    step('contracts/partial-render', function () {
      state.view = 'contracts'; state.mock.contracts = 'partial'; renderView(); renderCurrent();
      const rows = document.querySelectorAll('#contracts-body tr').length;
      const bad = document.querySelectorAll('#contracts-body tr.is-missing').length;
      const muted = document.querySelectorAll('#contracts-body tr.is-notplaceable').length;
      if (rows !== 30) { throw new Error('expected 30 rows, got ' + rows); }
      if (muted !== 5) { throw new Error('expected 5 not-placeable staff, got ' + muted); }
      return 'rows=' + rows + ' incomplete=' + bad + ' notplaceable=' + muted;
    });
    step('contracts/edit-cell', function () {
      const sel = document.querySelector('#contracts-body tr[data-staff="S-06"] select[data-f="primary"]');
      if (!sel) { throw new Error('S-06 primary select not found'); }
      sel.value = '保育士';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      const still = document.querySelectorAll('#contracts-body tr.is-missing').length;
      if (still !== 2) { throw new Error('expected 2 incomplete after fixing S-06, got ' + still); }
      return 'incomplete rows after edit=' + still;
    });
    step('contracts/save-blocked', function () {
      document.getElementById('contracts-save').click();
      const t = document.getElementById('contracts-msg').textContent;
      if (t.indexOf('保存できません') < 0) { throw new Error('expected blocked save, got: ' + t); }
      return t.replace(/\s+/g, ' ').trim().slice(0, 90);
    });
    step('contracts/reset', function () {
      document.getElementById('contracts-reset').click();
      return document.getElementById('contracts-msg').textContent.replace(/\s+/g, ' ').trim();
    });
    step('contracts/filter-noplaceable', function () {
      state.mock.contracts = 'all'; renderCurrent();
      const f = document.getElementById('contracts-filter');
      f.value = 'noplaceable';
      f.dispatchEvent(new Event('change', { bubbles: true }));
      const n = document.querySelectorAll('#contracts-body tr').length;
      f.value = 'all'; f.dispatchEvent(new Event('change', { bubbles: true }));
      if (n !== 5) { throw new Error('expected 5 not-placeable staff, got ' + n); }
      return 'not-placeable=' + n;
    });

    /* ---- generate: preconditions, progress, cancel ---- */
    step('generate/blocked-by-precondition', function () {
      state.view = 'generate'; state.mock.generate = 'ready'; renderView(); renderCurrent();
      const saved = JSON.parse(JSON.stringify(state.facilitySaved));
      state.facilitySaved.staffing_standard_key = '';
      document.getElementById('generate-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      const t = document.getElementById('generate-msg').textContent;
      if (t.indexOf('生成できません') < 0) { throw new Error('expected blocked generate, got: ' + t); }
      state.facilitySaved = saved;
      return t.replace(/\s+/g, ' ').trim().slice(0, 90);
    });
    step('generate/runs-progress', function () {
      renderCurrent();
      document.getElementById('generate-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      const box = document.getElementById('generate-progress');
      if (!box.querySelector('.progress__log')) { throw new Error('progress log missing'); }
      if (!document.getElementById('generate-run').disabled) { throw new Error('run button not disabled'); }
      return box.querySelector('.progress__log').textContent.split('\n').length + ' log lines';
    });
    step('generate/cancel', function () {
      document.getElementById('generate-cancel').click();
      return 'progress cleared=' + (document.getElementById('generate-progress').innerHTML === '');
    });

    /* ---- result: every state + day tabs + basis folds + approve ---- */
    step('result/clean', function () {
      state.view = 'result'; state.mock.result = 'clean'; renderView(); renderCurrent();
      const b = document.getElementById('result-body');
      const counts = {
        stat: b.querySelectorAll('.stat').length,
        reqRows: b.querySelectorAll('.grid-table tbody tr').length,
        gridCells: b.querySelectorAll('.shift-cell').length,
        gridRows: b.querySelectorAll('#shift-body tr').length,
        disclaimer: b.querySelectorAll('.disclaimer').length,
        folds: b.querySelectorAll('details.fold').length,
        days: b.querySelectorAll('#day-tabs .day-tab').length,
      };
      if (counts.gridCells === 0) { throw new Error('shift grid empty'); }
      if (counts.days !== SHIFT_DAYS.length) { throw new Error('day tabs ' + counts.days); }
      if (counts.gridRows !== placeableStaff().length) {
        throw new Error('grid rows ' + counts.gridRows + ' != placeable ' + placeableStaff().length);
      }
      return JSON.stringify(counts);
    });

    step('result/daily-hours-band', function () {
      const tally = bandTally(state.selectedDay);
      if (tally.total !== placeableStaff().length) { throw new Error('band total ' + tally.total); }
      if (tally.over10.length) {
        throw new Error('hard cap 10h violated in generated grid: ' + tally.over10.length);
      }
      const g = document.getElementById('gate-select');
      if (!g) { throw new Error('gate select missing'); }
      g.value = '8.75';
      g.dispatchEvent(new Event('change', { bubbles: true }));
      const after = document.getElementById('gate-select').value;
      if (after !== '8.75') { throw new Error('gate switch failed: ' + after); }
      g.value = '10';
      g.dispatchEvent(new Event('change', { bubbles: true }));
      return 'total=' + tally.total + ' band(8.75-10h)=' + tally.band.length +
        ' over10=' + tally.over10.length;
    });

    step('result/daily-hours-band-all-days', function () {
      /* 帯域は日付ごとに変わる。対象月の各日でハード制約10時間を超えないこと、
       * かつ「10hなら可 / 8.75hなら再配置」の帯域が実際に存在することを確認する。 */
      const perDay = SHIFT_DAYS.map(function (d) {
        const t = bandTally(d);
        if (t.over10.length) {
          throw new Error(d + ': ' + t.over10.length + ' staff over the 10h hard cap');
        }
        return d + '=' + t.band.length;
      });
      const anyBand = SHIFT_DAYS.some(function (d) { return bandTally(d).band.length > 0; });
      if (!anyBand) { throw new Error('no day has staff in the 8.75-10h band; the panel cannot inform the decision'); }
      return perDay.join(' ');
    });

    step('result/month-overtime-tally', function () {
      setLongDay(false);
      const t = monthBandTally();
      if (t.days !== 30) { throw new Error('month length ' + t.days); }
      if (t.rows.length !== placeableStaff().length) {
        throw new Error('month rows ' + t.rows.length + ' != placeable ' + placeableStaff().length);
      }
      /* 業務ルール2026-10-03: 時間外労働は「案」。毎日発生する前提なので
       * 勤務日数がすべて時間外労働日数になる。超過は止めない（BLOCKER にしない）。 */
      t.rows.forEach(function (r) {
        if (r.assumedDays !== r.worked) {
          throw new Error(r.name + ': assumed ' + r.assumedDays + ' != worked ' + r.worked);
        }
        if (r.overCap < 0) { throw new Error(r.name + ': negative overCap'); }
        if (r.over10 > 0) { throw new Error(r.name + ': ' + r.over10 + ' days over the 10h hard cap'); }
        if (r.severity !== 'OK') { throw new Error(r.name + ': severity ' + r.severity + ' (monthly must not block)'); }
      });
      if (t.hardViolations.length) { throw new Error('unexpected 10h violations: ' + t.hardViolations.length); }
      const el = document.getElementById('month-tally');
      if (!el) { throw new Error('month tally section missing'); }
      if (el.innerHTML.indexOf('月次の時間外労働日数') < 0) { throw new Error('month tally not rendered'); }
      return 'worked min=' + Math.min.apply(null, t.rows.map(function (r) { return r.worked; })) +
        ' max=' + Math.max.apply(null, t.rows.map(function (r) { return r.worked; })) +
        ' overCap=' + t.overCap.length + ' hardViolations=' + t.hardViolations.length;
    });

    step('result/daily-long-blocks-approval', function () {
      /* 1日10時間超は BLOCKER。園長でも確定できない。 */
      state.view = 'result'; state.mock.result = 'daily-long';
      renderView(); renderCurrent();
      const t = bandTally(state.selectedDay);
      if (!t.over10.length) { throw new Error('daily-long produced no 10h violation'); }
      state.viewer.principal = true;
      renderCurrent();
      const btn = document.getElementById('approve');
      if (!btn || !btn.disabled) { throw new Error('approve must be disabled on a 10h violation'); }
      const head = document.getElementById('result-state').textContent;
      if (head.indexOf('確定できません') < 0) { throw new Error('10h BLOCKER not surfaced'); }
      state.mock.result = 'clean'; renderCurrent();
      setLongDay(false); renderCurrent();
      return t.over10.length + ' staff over 10h, approve disabled for the 園長';
    });

    step('result/principal-only-approval', function () {
      /* 業務ルール2026-10-03: 園長の承認で確定。園長以外は確定できない。
         採用する上限は決定値（10時間＝BLOCKER）に固定して判定する。 */
      state.gate = '10';
      state.mock.result = 'clean'; setLongDay(false);
      state.viewer.principal = false; renderCurrent();
      const btn = document.getElementById('approve');
      if (!btn || !btn.disabled) { throw new Error('non-園長 must not be able to approve'); }
      const sel = document.getElementById('viewer-select');
      if (!sel) { throw new Error('viewer select missing'); }
      sel.value = 'principal';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      const btn2 = document.getElementById('approve');
      if (!btn2 || btn2.disabled) { throw new Error('園長 must be able to approve when there is no BLOCKER'); }
      state.viewer.principal = false;
      return 'general staff blocked, 園長 allowed';
    });
    step('result/day-switch', function () {
      const count = function (sel) { return document.querySelectorAll('#shift-body .' + sel).length; };
      const click = function (d) { document.querySelector('[data-day="' + d + '"]').click(); };
      click('2026-11-04');
      const workWed = count('shift-cell--work');
      click('2026-11-03');
      const offHoliday = count('shift-cell--off');
      const workHoliday = count('shift-cell--work');
      click('2026-11-04');
      const workBack = count('shift-cell--work');
      if (workWed !== workBack) { throw new Error('re-render not stable: ' + workWed + '/' + workBack); }
      if (workHoliday !== 0) { throw new Error('holiday should have no work cells, got ' + workHoliday); }
      return 'wed work=' + workWed + ' (blank=' + count('shift-cell--blank') +
        '), holiday all-off=' + offHoliday + ', back=' + workBack;
    });
    step('result/blocker-blocks-approve', function () {
      state.mock.result = 'blocker'; renderCurrent();
      const btn = document.getElementById('approve');
      if (!btn.disabled) { throw new Error('approve should be disabled when BLOCKER exists'); }
      const rows = document.querySelectorAll('#result-body .badge--danger').length;
      return 'approve disabled, danger badges=' + rows;
    });
    step('result/short-gap', function () {
      state.mock.result = 'short'; renderCurrent();
      return 'gap table rendered=' + (document.getElementById('result-body').innerHTML.indexOf('人手不足') >= 0);
    });
    step('result/gate-changes-approval', function () {
      /* 採用する上限が BLOCKER/WARNING の数と確定可否に反映されることを確かめる。
         8.75〜10時間の帯域に職員が1名いるので、8時間45分だと BLOCKER になる。 */
      state.mock.result = 'clean'; setLongDay(false);
      state.viewer.principal = true;
      const read = function (gate) {
        state.gate = gate; renderCurrent();
        const body = document.getElementById('result-body').textContent;
        const bw = body.match(/BLOCKER \/ WARNING\s*([\d]+)\s*\/\s*([\d]+)/);
        return {
          bw: bw ? bw[1] + '/' + bw[2] : '?',
          disabled: document.getElementById('approve').disabled,
        };
      };
      const at10 = read('10');
      const at875 = read('8.75');
      const off = read('off');
      state.gate = '10'; renderCurrent();
      if (at10.bw === at875.bw) {
        throw new Error('gate must change BLOCKER/WARNING: both ' + at10.bw);
      }
      if (at10.disabled) { throw new Error('10h gate should allow approval when clean'); }
      if (!at875.disabled) { throw new Error('8.75h gate must block approval (band staff becomes BLOCKER)'); }
      if (off.disabled) { throw new Error('off gate should not block approval'); }
      return '10h=' + at10.bw + '(確定可) / 8.75h=' + at875.bw + '(確定不可) / off=' + off.bw;
    });

    step('result/approve-marks-approved', function () {
      state.gate = '10';
      state.mock.result = 'clean'; setLongDay(false);
      state.viewer.principal = true; renderCurrent();
      const btn = document.getElementById('approve');
      if (!btn || btn.disabled) { throw new Error('approve must be enabled for the 園長 when clean'); }
      btn.click();
      const card = btn.closest('.card');
      const msg = card.querySelector('.msg');
      if (!msg || msg.textContent.indexOf('確定状態') < 0) {
        throw new Error('approve click did not report a confirmed state');
      }
      return 'confirmed: ' + msg.textContent.replace(/\s+/g, ' ').trim().slice(0, 60);
    });

    const failed = REPORT.filter(function (r) { return !r.ok; });
    const pre = document.createElement('pre');
    pre.id = 'selftest-out';
    pre.textContent = JSON.stringify({
      total: REPORT.length,
      failed: failed.length,
      results: REPORT,
    }, null, 1);
    document.body.appendChild(pre);
  }, 300);
});
