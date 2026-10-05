/* Confirmation-mock behaviour. No network, no persistence, no CBC execution.
 * CSP forbids inline scripts, so every listener is attached with addEventListener.
 */
'use strict';

const VIEWS = ['arrival', 'facility', 'contracts', 'generate', 'result'];

const MOCK_STATES = {
  arrival: [
    { id: 'default', label: '入力済み（既定値と例外日がある）' },
    { id: 'empty', label: '未入力（全員が保育必要量区分にフォールバック）' },
    { id: 'partial', label: '一部入力（5名だけ既定値あり）' },
    { id: 'invalid', label: 'エラー（閉園より後・開園より前・対象月外の例外日）' },
  ],
  facility: [
    { id: 'default', label: '入力済み（現在の設定）' },
    { id: 'empty', label: '未入力（開園・閉園・定員・配置基準・実行時間の上限が空）' },
    { id: 'partial', label: '一部入力（閉園・定員が空）' },
    { id: 'invalid', label: 'エラー（閉園時刻が開園時刻より前）' },
  ],
  contracts: [
    { id: 'all', label: '入力済み（30名全員）' },
    { id: 'partial', label: '一部入力（資格なし1名・時間未入力1名・職務未入力1名）' },
    { id: 'empty', label: '未入力（全員空欄）' },
    { id: 'invalid', label: 'エラー（時間0・始業終業が逆・資格なし）' },
  ],
  generate: [
    { id: 'ready', label: '入力済み（生成できる状態）' },
    { id: 'empty', label: '未入力（対象月が空）' },
    { id: 'blocked', label: 'エラー（前提が未入力：施設設定・職員契約）' },
    { id: 'running', label: '生成中（進捗を表示）' },
    { id: 'done', label: '生成完了（BLOCKER なし）' },
    { id: 'blocker', label: '生成完了（BLOCKER あり）' },
    { id: 'failed', label: '求解失敗（解なし）' },
    { id: 'nocbc', label: 'CBC 不在（機能を利用不可）' },
  ],
  result: [
    { id: 'clean', label: 'BLOCKER なし（参考値として確定可能）' },
    { id: 'blocker', label: 'BLOCKER あり（配置基準を満たさない）' },
    { id: 'short', label: '人手不足あり（gap と WARNING）' },
    { id: 'daily-long', label: '1日10時間超の例（BLOCKER）' },
    { id: 'failed', label: '求解失敗（結果なし）' },
  ],
};

const FACILITY_VARIANTS = {
  default: FACILITY_DEFAULT,
  empty: FACILITY_EMPTY,
  partial: FACILITY_PARTIAL,
  invalid: FACILITY_INVALID,
};

function staffVariant(id) {
  const base = {
    all: STAFF_ALL,
    partial: STAFF_PARTIAL,
    empty: STAFF_EMPTY,
    invalid: STAFF_INVALID,
  };
  return (base[id] || STAFF_ALL).map(function (s) { return Object.assign({}, s); });
}

const state = {
  view: 'arrival',
  mock: { arrival: 'default', facility: 'default', contracts: 'all', generate: 'ready', result: 'clean' },
  children: childVariant('default'),
  childrenSaved: childVariant('default'),
  overrides: overridesVariant('default'),
  overridesSaved: overridesVariant('default'),
  arrivalFilter: 'all',
  arrivalDay: '2026-11-04',
  facility: Object.assign({}, FACILITY_DEFAULT, { closed_days: FACILITY_DEFAULT.closed_days.slice() }),
  facilitySaved: JSON.parse(JSON.stringify(FACILITY_DEFAULT)),
  staff: staffVariant('all'),
  staffSaved: staffVariant('all'),
  generate: { target_month: '2026-11', staffing_standard_key: '福岡市', relax_level: '0' },
  /* 未確定事項2: 1日の労働時間の上限。'10' | '8.75' | 'off' */
  gate: '10',
  /* 業務ルール 2026-10-03: 園長の承認で確定。principal=true のときだけ確定できる */
  viewer: { principal: true },
  selectedDay: REQUIREMENT_DAY,
};

const $ = function (sel, root) { return (root || document).querySelector(sel); };
const $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
const esc = function (s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
};
const hhmm = function (v) { return /^\d{2}:\d{2}$/.test(v || '') ? v : ''; };
const num = function (v) { const n = parseFloat(v); return isFinite(n) ? n : null; };
const pad = function (n) { return n < 10 ? '0' + n : String(n); };
function weekdayOf(iso) {
  const d = new Date(iso + 'T00:00:00');
  return ['日', '月', '火', '水', '木', '金', '土'][d.getDay()];
}

/* ============================ 状態パネル ============================ */
function renderStateOptions() {
  const sel = $('#mock-state');
  sel.innerHTML = MOCK_STATES[state.view]
    .map(function (s) {
      return '<option value="' + esc(s.id) + '">' + esc(s.label) + '</option>';
    }).join('');
  sel.value = state.mock[state.view];
}
/* The sidebar has one entry for the whole module, so keep it highlighted on every screen. */
function renderView() {
  VIEWS.forEach(function (v) {
    const el = document.getElementById('view-' + v);
    if (el) { el.hidden = (v !== state.view); }
  });
  $$('[data-nav]').forEach(function (a) { a.removeAttribute('title'); });
  const nav = $('[data-nav="arrival"]');
  if (nav) { nav.title = '確認中の画面'; }
  $('#mock-view').value = state.view;
  renderStateOptions();
}

/* ============================ 画面2 施設設定 ============================ */
function fillSelect(sel, options, value) {
  sel.innerHTML = options.map(function (o) {
    const v = typeof o === 'string' ? o : o.value;
    const t = typeof o === 'string' ? o : o.label;
    return '<option value="' + esc(v) + '">' + esc(t) + '</option>';
  }).join('');
  if (value != null) { sel.value = value; }
}

function loadFacility(variantId) {
  const src = FACILITY_VARIANTS[variantId] || FACILITY_DEFAULT;
  const form = $('#facility-form');
  form.day_open.value = src.day_open || '';
  form.day_close.value = src.day_close || '';
  form.granularity_min.value = src.granularity_min;
  form.capacity.value = src.capacity || '';
  form.time_limit_sec.value = src.time_limit_sec || '';
  form.relax_level.value = src.relax_level;
  form.enforce_min_two.checked = !!src.enforce_min_two;
  fillSelect($('#standard-select'), [{ value: '', label: '（未選択）' }].concat(
    STANDARDS.map(function (s) { return { value: s.key, label: s.name }; })), src.staffing_standard_key);
  state.facility.closed_days = src.closed_days.map(function (d) { return Object.assign({}, d); });
  renderClosedDays();
  renderStandardNote();
  $('#facility-msg').innerHTML = '';
  validateFacility(true);
}

function renderStandardNote() {
  const key = $('#standard-select').value;
  const s = STANDARDS.filter(function (x) { return x.key === key; })[0];
  $('#standard-source').textContent = s ? '根拠：' + s.source : '未選択です。';
  $('#standard-summary').innerHTML = s
    ? '<p style="margin:0">' + esc(s.summary) + '</p>'
    : '<p style="margin:0">配置基準が未選択です。このままでは生成できません。</p>';
}

function renderClosedDays() {
  const box = $('#closed-day-list');
  if (!state.facility.closed_days.length) {
    box.innerHTML = '<span style="color:var(--muted);font-size:0.82rem">休園日・祝日の登録はありません。</span>';
    return;
  }
  box.innerHTML = state.facility.closed_days.map(function (d, i) {
    return '<span class="chip chip--' + esc(d.kind) + '">' +
      esc(d.date) + '（' + weekdayOf(d.date) + '）' + esc(d.label) +
      ' <span class="chip__x" data-remove-day="' + i + '" role="button" tabindex="0" aria-label="削除">×</span></span>';
  }).join('');
}

function validateFacility(quiet) {
  const form = $('#facility-form');
  const problems = [];
  const open = hhmm(form.day_open.value);
  const close = hhmm(form.day_close.value);
  if (!open) { problems.push('開園時刻を入力してください'); }
  if (!close) { problems.push('閉園時刻を入力してください'); }
  if (open && close && close <= open) { problems.push('閉園時刻は開園時刻より後にしてください'); }
  if (!num(form.capacity.value)) { problems.push('定員を入力してください'); }
  if (!form.staffing_standard_key.value) { problems.push('配置基準を選択してください'); }
  const limit = num(form.time_limit_sec.value);
  if (limit == null) { problems.push('実行時間の上限を入力してください'); }
  else if (limit < 5 || limit > 300) { problems.push('実行時間の上限は5〜300秒で入力してください'); }
  if (!quiet) {
    const box = $('#facility-msg');
    box.innerHTML = problems.length
      ? '<p class="msg msg--danger"><strong>保存できません。</strong><br>' + problems.map(esc).join('<br>') + '</p>'
      : '<p class="msg msg--ok">保存しました（このモックでは画面内のメモのみです）。</p>';
  }
  /* Name the offending fields, not just the count: the reviewer must see which input
   is wrong on a state switch, before pressing 保存する. */
  $('#facility-state').innerHTML = problems.length
    ? '<div class="note note--danger" style="margin-bottom:1rem">' +
      '<strong>未入力・不備が ' + problems.length + ' 件あります。</strong>' +
      '<ul style="margin:.4rem 0 0 1.1rem;padding:0">' +
      problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') +
      '</ul></div>'
    : '';
  return problems;
}

function facilityAudit() {
  const f = state.facilitySaved;
  const problems = validateFacilityQuiet(f);
  const lines = [];
  lines.push('現在の保存値（入力済みの状態）: 開園 ' + (f.day_open || '未入力') +
    ' / 閉園 ' + (f.day_close || '未入力') + ' / 粒度 ' + f.granularity_min + '分' +
    ' / 定員 ' + (f.capacity || '未入力') + ' / 配置基準 ' + (f.staffing_standard_key || '未選択'));
  lines.push('2名ルール: ' + (f.enforce_min_two ? '適用する' : '適用しない'));
  lines.push('実行時間の上限: ' + (f.time_limit_sec || '未入力') + '秒 / 緩和 L' + f.relax_level);
  lines.push('休園日・祝日: ' + (f.closed_days.length ? f.closed_days.length + '件' : 'なし'));
  $('#facility-audit').innerHTML =
    '<div class="card"><h2 class="card__title">保存値と確認</h2><div class="note"><p style="margin:0 0 .4rem">' +
    lines.map(esc).join('<br>') + '</p>' +
    (problems.length
      ? '<p class="msg msg--danger" style="margin-top:.5rem">未解決: ' + problems.map(esc).join(' / ') + '</p>'
      : '<p class="msg msg--ok" style="margin-top:.5rem">生成に必要な項目はすべてそろっています。</p>') +
    '</div></div>';
}

function validateFacilityQuiet(f) {
  const problems = [];
  if (!f.day_open) { problems.push('開園時刻'); }
  if (!f.day_close) { problems.push('閉園時刻'); }
  if (f.day_open && f.day_close && f.day_close <= f.day_open) { problems.push('閉園>開園'); }
  if (!f.capacity) { problems.push('定員'); }
  if (!f.staffing_standard_key) { problems.push('配置基準'); }
  if (!f.time_limit_sec) { problems.push('実行時間上限'); }
  return problems;
}

/* ======================= 画面3 職員契約・資格 ======================= */
function staffProblems(s) {
  const p = [];
  if (!s.primary) { p.push('資格（主）'); }
  if (!s.employment) { p.push('雇用形態'); }
  const w = num(s.weekly), d = num(s.daily);
  if (w == null) { p.push('週契約時間'); }
  else if (w <= 0) { p.push('週契約時間>0'); }
  if (d == null) { p.push('1日契約時間'); }
  else if (d <= 0) { p.push('1日契約時間>0'); }
  if (hhmm(s.earliest) && hhmm(s.latest) && s.latest <= s.earliest) { p.push('最遅終業>最早始業'); }
  return p;
}

function renderContracts() {
  const filter = $('#contracts-filter').value;
  const rows = state.staff.filter(function (s) {
    const probs = staffProblems(s);
    if (filter === 'incomplete') { return probs.length > 0; }
    if (filter === 'noplaceable') { return NOT_PLACEABLE.indexOf(s.primary) >= 0; }
    return true;
  });
  $('#contracts-body').innerHTML = rows.map(function (s) {
    const probs = staffProblems(s);
    const placeable = NOT_PLACEABLE.indexOf(s.primary) < 0;
    const cls = !placeable ? 'is-notplaceable' : (probs.length ? 'is-missing' : '');
    const bad = function (field) { return probs.indexOf(field) >= 0 ? ' is-invalid' : ''; };
    return '<tr class="' + cls + '" data-staff="' + esc(s.id) + '">' +
      '<td><strong>' + esc(s.name) + '</strong><br><span style="color:var(--muted);font-size:.72rem">' + esc(s.id) + '</span></td>' +
      '<td><select data-f="primary">' + [''].concat(ROLES).map(function (r) {
        return '<option' + (r === s.primary ? ' selected' : '') + '>' + esc(r) + '</option>';
      }).join('') + '</select></td>' +
      '<td><select data-f="secondary">' + [''].concat(ROLES).map(function (r) {
        return '<option' + (r === s.secondary ? ' selected' : '') + '>' + esc(r) + '</option>';
      }).join('') + '</select></td>' +
      '<td><select data-f="employment">' + [''].concat(EMPLOYMENT.map(function (e) { return e.name; })).map(function (e) {
        return '<option' + (e === s.employment ? ' selected' : '') + '>' + esc(e) + '</option>';
      }).join('') + '</select></td>' +
      '<td><input data-f="weekly" value="' + esc(s.weekly) + '" inputmode="decimal" class="' + bad('週契約時間') + bad('週契約時間>0') + '"></td>' +
      '<td><input data-f="daily" value="' + esc(s.daily) + '" inputmode="decimal" class="' + bad('1日契約時間') + bad('1日契約時間>0') + '"></td>' +
      '<td><input data-f="maxDays" value="' + esc(s.maxDays) + '" inputmode="numeric"></td>' +
      '<td><input data-f="maxConsec" value="' + esc(s.maxConsec) + '" inputmode="numeric"></td>' +
      '<td><input data-f="earliest" type="time" value="' + esc(s.earliest) + '" class="' + bad('最遅終業>最早始業') + '"></td>' +
      '<td><input data-f="latest" type="time" value="' + esc(s.latest) + '" class="' + bad('最遅終業>最早始業') + '"></td>' +
      '<td>' + (placeable && s.primary
        ? '<span class="badge badge--ok">配置対象</span>'
        : (s.primary
          ? '<span class="badge badge--muted">配置対象外</span>'
          : '<span class="badge badge--danger">資格なし</span>')) + '</td>' +
      '</tr>';
  }).join('');

  const placeableStaff = state.staff.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0; });
  const incomplete = placeableStaff.filter(function (s) { return staffProblems(s).length; }).length;
  const notPlaceable = state.staff.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) >= 0; }).length;
  $('#contracts-count').textContent =
    '全 ' + state.staff.length + ' 名（表示 ' + rows.length + ' 名）／配置対象 ' + placeableStaff.length +
    ' 名・未入力あり ' + incomplete + ' 名／配置対象外の職種 ' + notPlaceable + ' 名';

  if (incomplete) {
    $('#contracts-state').innerHTML =
    '<div class="note note--warn"><p style="margin:0 0 .3rem">配置対象の ' + incomplete +
      ' 名に未入力の項目があります。資格が無い職員はシフト枠に配置されません（' +
      'shiftai 側で ValueError になります）。配置対象外の職種は計算に使いません。</p></div>';
  } else {
    $('#contracts-state').innerHTML = '';
  }

  const blockers = [];
  if (!state.facilitySaved.staffing_standard_key) { blockers.push('施設設定の配置基準が未選択'); }
  const saved = validateFacilityQuiet(state.facilitySaved);
  saved.forEach(function (p) { blockers.push('施設設定: ' + p); });
  const placeableIncomplete = state.staff.filter(function (s) {
    return NOT_PLACEABLE.indexOf(s.primary) < 0 && staffProblems(s).length > 0;
  });
  placeableIncomplete.forEach(function (s) { blockers.push(s.name + '（' + staffProblems(s).join('、') + '）'); });

  $('#contracts-audit').innerHTML =
    '<div class="card"><h2 class="card__title">生成できるかの確認</h2>' +
    (blockers.length
      ? '<div class="note note--warn"><p style="margin:0 0 .3rem">次のため生成できません。</p><ul style="margin:.2rem 0 0 1.1rem;padding:0">' +
        blockers.map(function (b) { return '<li>' + esc(b) + '</li>'; }).join('') + '</ul></div>'
      : '<div class="note note--ok">配置対象の職員 ' +
        state.staff.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0; }).length +
        ' 名はすべてcontract 整っています。</div>') +
    '</div>';
}

/* ============================ 画面4 生成 ============================ */
function loadGenerate(variantId) {
  const form = $('#generate-form');
  $('#generate-progress').innerHTML = '';
  $('#generate-msg').innerHTML = '';
  $('#generate-joblist').innerHTML = '';
  fillSelect($('#generate-standard'), [{ value: '', label: '（未選択）' }].concat(
    STANDARDS.map(function (s) { return { value: s.key, label: s.name }; })), '');

  const g = state.generate;
  if (variantId === 'empty') { g.target_month = ''; }
  else { g.target_month = '2026-11'; }
  if (variantId === 'ready' || variantId === 'done' || variantId === 'blocker' ||
      variantId === 'running' || variantId === 'failed' || variantId === 'nocbc') {
    g.staffing_standard_key = state.facilitySaved.staffing_standard_key || '福岡市';
  } else {
    g.staffing_standard_key = '';
  }
  form.target_month.value = g.target_month;
  form.staffing_standard_key.value = g.staffing_standard_key;

  renderGenerateInputs(variantId);
  renderGenerateJobs(variantId);
  applyGenerateButton(variantId);
  if (variantId === 'running') { runProgress(form); }
}

/* Disable the button in states that cannot run, and state the reason once, in one place.
   'failed' means "no solution found", so the reviewer must be able to press it again. */
function generateBlockedReason(variantId) {
  if (variantId === 'empty') { return '対象月を入力してください。'; }
  if (variantId === 'blocked') { return '前提データが未入力なので生成できません。'; }
  if (variantId === 'nocbc') { return 'CBC が利用できないため生成できません。'; }
  return null;
}

function applyGenerateButton(variantId) {
  const btn = $('#generate-run');
  const reason = generateBlockedReason(variantId);
  btn.disabled = !!reason;
  btn.title = reason || '';
  const hint = $('#generate-blocked');
  if (hint) {
    hint.textContent = reason ? ('この状態では生成できません: ' + reason) : '';
    hint.hidden = !reason;
  }
}

function renderGenerateInputs(variantId) {
  const saved = state.facilitySaved;
  const placeable = state.staff.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0; });
  const ready = placeable.filter(function (s) { return staffProblems(s).length === 0; });
  const missingQual = state.staff.filter(function (s) { return !s.primary; });
  const fallback = Math.max(0, CHILD_COUNT.total - CHILD_COUNT.early - CHILD_COUNT.late);

  let html = '<div class="card"><h2 class="card__title">生成に使うデータ</h2><div class="note"><ul style="margin:0 0 0 .1rem;padding-left:1.1rem">' +
    '<li>対象月: <strong>' + esc(state.generate.target_month || '未入力') + '</strong></li>' +
    '<li>配置基準: <strong>' + esc(state.generate.staffing_standard_key || '未選択') + '</strong>' +
    '（施設設定の保存値: ' + esc(saved.staffing_standard_key || '未選択') + '）</li>' +
    '<li>在園予定: ' + CHILD_COUNT.total + '名（保育標準時間 ' + CHILD_COUNT.standard +
    ' / 保育短時間 ' + CHILD_COUNT.short + '）</li>' +
    '<li>うち朝延長 ' + CHILD_COUNT.early + '名・夕延長 ' + CHILD_COUNT.late + '名</li>' +
    '<li>配置対象の職員: <strong>' + ready.length + '</strong> / ' + placeable.length + '名</li>' +
    (missingQual.length
      ? '<li style="color:var(--danger)">資格が未入力で除外される職員: ' +
        missingQual.map(function (s) { return esc(s.name); }).join('、') + '</li>'
      : '') +
    '<li style="color:var(--muted)">登園予定が未設定で保育標準時間から補完する園児: 約 ' + fallback + '名</li>' +
    '</ul></div>';
  html += '</div>';
  $('#generate-inputs').innerHTML = html;
}

function renderGenerateJobs(variantId) {
  const rows = {
    ready: [], empty: [], blocked: [],
    running: [{ status: 'running', month: '2026-11', at: '生成中', by: '確認用園長' }],
    done: [{ status: 'succeeded', month: '2026-11', at: '2026-10-03 09:14', by: '確認用園長', secs: '18.4秒' }],
    blocker: [{ status: 'succeeded', month: '2026-11', at: '2026-10-03 09:14', by: '確認用園長', secs: '21.7秒' }],
    failed: [{ status: 'failed', month: '2026-11', at: '2026-10-03 09:14', by: '確認用園長', secs: '30.0秒' }],
    nocbc: [],
  };
  const list = rows[variantId] || [];
  const badge = { running: 'warn', succeeded: 'ok', failed: 'danger' };
  const label = { running: '計算中', succeeded: '完了', failed: '失敗' };
  $('#generate-joblist').innerHTML =
    '<div class="card"><h2 class="card__title">生成の履歴</h2>' +
    (list.length
      ? '<div class="table-wrap"><table class="grid-table"><thead><tr>' +
        '<th>対象月</th><th>状態</th><th>時刻</th><th>実行者</th><th>所要</th></tr></thead><tbody>' +
        list.map(function (j) {
          return '<tr><td>' + esc(j.month) + '</td>' +
            '<td><span class="badge badge--' + badge[j.status] + '">' + label[j.status] + '</span></td>' +
            '<td>' + esc(j.at) + '</td><td>' + esc(j.by) + '</td><td>' + esc(j.secs || '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>'
      : '<p style="color:var(--muted);font-size:.85rem;margin:0">まだ生成していません。</p>') +
    '</div>';
}

function preconditions() {
  const problems = [];
  validateFacilityQuiet(state.facilitySaved).forEach(function (p) {
    problems.push('施設設定が未完了（' + p + '）');
  });
  state.staff.forEach(function (s) {
    if (NOT_PLACEABLE.indexOf(s.primary) >= 0) { return; }
    const p = staffProblems(s);
    if (p.length) { problems.push(s.name + ' の契約が未完了（' + p.join('、') + '）'); }
  });
  if (!state.staff.some(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0 && s.primary; })) {
    problems.push('配置可能な職員が1名もいません');
  }
  return problems;
}

function runProgress(form) {
  const limit = parseInt(state.facilitySaved.time_limit_sec || '30', 10);
  const box = $('#generate-progress');
  box.innerHTML =
    '<div class="card"><h2 class="card__title">計算中</h2>' +
    '<p style="font-size:.85rem;margin:0 0 .5rem">画面を閉じても計算は続きます。園の他の操作には影響しません。</p>' +
    '<div class="progress"><div class="progress__bar"><div class="progress__fill" id="pf" style="width:4%"></div></div>' +
    '<p style="font-size:.78rem;color:var(--muted);margin:.35rem 0 0" id="pl">0% ／ 上限 ' + limit + '秒</p></div>' +
    '<pre class="progress__log" id="log">求人を組み立てています…</pre></div>';
  $('#generate-run').disabled = true;

  const steps = [
    [12, '在園予定を時間帯に展開しています…'],
    [26, '保育必要量から配置基準を計算しています…'],
    [40, '保育標準時間帯に絞っています…'],
    [58, '延長保育する時間帯を確認しています…'],
    [74, '最適化しています（CBC 起動）…'],
    [88, '解を検証しています…'],
    [100, '完了しました。'],
  ];
  let i = 0;
  const timer = setInterval(function () {
    i += 1;
    if (i >= steps.length) { clearInterval(timer); return; }
    const pct = steps[i][0];
    const fill = $('#pf'), label = $('#pl'), log = $('#log');
    if (!fill) { clearInterval(timer); return; }
    fill.style.width = pct + '%';
    label.textContent = pct + '% ／ 上限 ' + limit + '秒';
    log.textContent += '\n' + steps[i][1];
  }, 420);
}

function renderGenerateErrors(variantId) {
  const box = $('#generate-msg');
  if (variantId === 'empty') {
    box.innerHTML = '<p class="msg msg--warn">対象月を入力してください。</p>';
  } else if (variantId === 'blocked') {
    const p = preconditions();
    box.innerHTML = '<p class="msg msg--danger"><strong>生成できません。</strong><br>' +
      (p.length ? p.map(esc).join('<br>') : '前提データが未入力です。') + '</p>';
  } else if (variantId === 'nocbc') {
    box.innerHTML = '<p class="msg msg--danger"><strong>生成できません。</strong><br>' +
      'CBC（シフト計算ライブラリ）が見つかりません。この場合、シフトの生成も検証もできません。<br>' +
      '園の他の機能は通常どおり使えます。</p>';
  } else if (variantId === 'failed') {
    box.innerHTML = '<p class="msg msg--danger">30秒以内に解が見つかりませんでした。' +
      '緩和の段階を L1 以上にするか、配置基準・職員契約を確認してください。</p>';
  } else if (variantId === 'blocker') {
    box.innerHTML = '<p class="msg msg--warn">生成は完了しましたが <strong>BLOCKER が 2件</strong> あります。' +
      '「5 生成結果」で内容を確認してください。このままでは確定できません。</p>';
  } else if (variantId === 'done') {
    box.innerHTML = '<p class="msg msg--ok">生成が完了しました。「5 生成結果」を確認してください。</p>';
  } else {
    box.innerHTML = '';
  }
}

/* ============================ 画面5 結果 ============================ */
function renderResult(variantId) {
  const sub = $('#result-sub');
  const body = $('#result-body');
  const stateBox = $('#result-state');
  /* daily-long は1日10時間超を出す例。それ以外は通常の上書きなし */
  setLongDay(variantId === 'daily-long');
  if (variantId === 'failed') {
    sub.textContent = '2026年11月 ／ 全国基準（厚労省）';
    stateBox.innerHTML = '<div class="note note--danger" style="margin-bottom:1rem">' +
      '生成に失敗しました。結果は保存されていません。職員契約を確認するか、緩和の段階を上げて再実行してください。</div>';
    body.innerHTML = '';
    return;
  }

  sub.textContent = '2026年11月 ／ ' + state.generate.staffing_standard_key + ' ／ 2026-10-03 09:14 生成';
  const violations = variantId === 'blocker' ? VIOLATIONS_BLOCKER : VIOLATIONS_CLEAN;
  const blockers = violations.filter(function (v) { return v.severity === 'BLOCKER'; });
  const warnings = violations.filter(function (v) { return v.severity === 'WARNING'; });
  /* BLOCKER を持つ状態では、人手不足も同じ時間帯を指しているため併せて表示する */
  const gaps = (variantId === 'short' || variantId === 'blocker') ? GAP_ROWS_SHORT : GAP_ROWS_OK;
  /* 月次の時間外労働は「案」なので超過では止めない。止めるのは採用した上限が示す閾値だけ。 */
  const gateT = gateSeverity(monthBandTally(), state.gate);
  const monthBlockers = gateT.blockers.length;
  const monthWarnings = gateT.warnings.length;
  const monthWarningTotal = warnings.length + monthWarnings;
  const hasBlocker = blockers.length + monthBlockers > 0;

  stateBox.innerHTML = hasBlocker
    ? '<div class="note note--danger" style="margin-bottom:1rem"><strong>BLOCKER が ' +
      (blockers.length + monthBlockers) + ' 件あるため、このシフト案は確定できません。</strong>' +
      (monthBlockers
        ? 'うち ' + monthBlockers + ' 名が採用した上限（' + gateT.rule.label + '）で BLOCKER です。'
        : (monthWarnings
          ? '採用した上限（' + gateT.rule.label + '）で WARNING が ' + monthWarnings + ' 名です。確定はできます。'
          : '')) +
      '共有する前に配置基準・職員契約を確認してください。</div>'
    : '<div class="note note--ok" style="margin-bottom:1rem">BLOCKER はありません。' +
      'ただし参考値です。確定の判断は園長が行ってください。</div>';

  const placeable = state.staff.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0; });

  const cost = placeable.reduce(function (sum, s) {
    const coef = (EMPLOYMENT.filter(function (e) { return e.name === s.employment; })[0] || { coefficient: 1 }).coefficient;
    const hours = s.employment === '正職員' ? 40 : (num(s.weekly) || 0);
    return sum + hours * coef * 1500;
  }, 0);

  let html =
    '<div class="disclaimer"><h3>この結果は参考値です</h3>' +
    '<p>保育所の職員配置基準と労働基準法をもとに計算した<strong>案</strong>です。' +
    '法令適合を保証するものではありません。実際の勤務安排は園の責任者が判断してください。' +
    '自動保存も自動確定も行いません。</p></div>' +

    '<div class="summary">' +
    '<div class="stat"><p class="stat__label">状態</p><p class="stat__value">' +
    (hasBlocker ? '<span class="stat__value--danger">下書き</span>' : '<span class="stat__value--ok">下書き</span>') +
    '</p><p class="stat__note">' + (hasBlocker ? 'BLOCKER あり' : 'BLOCKER なし') + '</p></div>' +
    '<div class="stat"><p class="stat__label">配置対象の職員</p><p class="stat__value">' + placeable.length + '</p>' +
    '<p class="stat__note">／ 配置対象外 ' + (state.staff.length - placeable.length) + '名</p></div>' +
'<div class="stat"><p class="stat__label">BLOCKER / WARNING</p><p class="stat__value' +
    (hasBlocker ? ' stat__value--danger' : (monthWarningTotal ? ' stat__value--warn' : '')) + '">' +
    (blockers.length + monthBlockers) + ' / ' + monthWarningTotal + '</p><p class="stat__note">' +
    esc(gateT.rule.label) + '＋全21種類の判定</p></div>' +
    '<div class="stat"><p class="stat__label">月額人件費の目安</p><p class="stat__value">' +
    Math.round(cost / 10000).toLocaleString() + '万円</p><p class="stat__note">1,500円/時・雇用形態係数別</p></div>' +
    '</div>';

  /* --- requirement table with basis --- */
  html += '<div class="card"><h2 class="card__title">必要人員（配置基準の算出結果）</h2>' +
    '<p style="font-size:.82rem;color:var(--ink-2);margin:0 0 .6rem">' +
    esc(REQUIREMENT_DAY) + '（' + weekdayOf(REQUIREMENT_DAY) + '）の例です。' +
    '各数値の「根拠」を押すと、算出の式と適用した基準が表示されます。</p>' +
    '<div class="table-wrap"><table class="grid-table"><thead><tr>' +
    '<th>時間帯</th><th>保育標準／延長</th><th>年齢</th><th>必要職員数</th><th>必要保育士数</th><th>根拠</th>' +
    '</tr></thead><tbody>';
  REQUIREMENT_ROWS.forEach(function (r, i) {
    const kind = r.slot < '08:30' ? '早朝保育' : (r.slot < '16:30' ? '保育標準時間' : '延長保育');
    const qualified = r.age === '0歳児' || r.age === '1・2歳児' || r.age === '3歳児'
      ? Math.max(1, r.need - 1) : r.need;
    html += '<tr><td>' + esc(r.slot) + '</td><td>' + kind + '</td><td>' + esc(r.age) + '</td>' +
      '<td><strong>' + r.need + '</strong></td><td>' + qualified + '</td>' +
      '<td><details class="fold"><summary>表示</summary>' +
      '<p class="basis-text">' + esc(r.basis) + '</p></details></td></tr>';
  });
  html += '</tbody></table></div></div>';

  /* --- shift grid --- */
  html += '<div class="card"><h2 class="card__title">シフト案</h2>' +
    '<div class="day-tabs" id="day-tabs">' +
    SHIFT_DAYS.map(function (d) {
      const label = d.slice(5).replace('-', '/');
      return '<button type="button" class="day-tab' + (d === state.selectedDay ? ' is-active' : '') +
        '" data-day="' + d + '">' + label + '<small>' + weekdayOf(d) +
        (d === '2026-11-03' ? ' 祝日' : '') + '</small></button>';
    }).join('') + '</div>' +
    '<div class="shift-wrap"><table class="shift-table"><thead><tr><th>職員</th>' +
    SLOTS.map(function (s, i) {
      const k = SLOT_KIND[i];
      const cls = k === '早朝保育' ? ' is-kind-early' : (k === '延長保育' ? ' is-kind-late' : '');
      return '<th class="' + cls.trim() + '">' + s + '</th>';
    }).join('') + '</tr></thead><tbody id="shift-body"></tbody></table></div>' +
    '<div class="shift-legend">' +
    '<span><i class="shift-cell--work"></i>勤務</span>' +
    '<span><i class="shift-cell--off"></i>休み</span>' +
    '<span><i class="shift-cell--blank"></i>未割当（人が足りない）</span>' +
    '<span><i class="legend-early"></i>早朝保育の時間帯</span>' +
    '<span><i class="legend-late"></i>延長保育の時間帯</span>' +
    '</div>' +
    '<p style="font-size:.78rem;color:var(--muted);margin:.6rem 0 0">' +
    '1マス=30分。勤務は引き継ぎの時間を除いた合計で計算しています。' +
    '未割当（赤）は人が足りない時間帯です。</p>' +
    '</div>';

  /* --- 1日の労働時間（未確定事項2 の帯域） --- */
  const tally = bandTally(state.selectedDay);
  const gateLabel = {
    '10': '10時間（法定上限で止める）',
    '8.75': '8時間45分で止める（法定上限は無視）',
    'off': '判定しない（参考値のみ）',
  }[state.gate];
  html += '<div class="card"><h2 class="card__title">1日の労働時間の上限（' + esc(state.selectedDay) + '）</h2>' +
    '<div class="note"><p style="margin:0 0 .4rem">' +
    'shiftai は意図的に複数の閾値を持ちます。' +
    '<strong>10.0時間</strong>が労働基準法32条・34条のハード制約（' +
    '<code>config.py:41</code>）、<strong>8.75時間</strong>が休憩45分を加えた' +
    '適合判定（<code>config.py:49</code>）、<strong>9.0時間</strong>はソルバ内部の' +
    'ペナルチ目安で判定には使いません（<code>config.py:54</code>）。' +
    '<strong>8.75〜10時間の帯域をどうするかが要点です。</strong>' +
    '2026-10-03 の決定: 「10時間超＝BLOCKER、8時間45分超＝WARNING」としました。' +
    '下の選択で比べられます。8時間45分を BLOCKER にすると正職員のほぼすべての日が確定できなくなります。' +
    '選択を変えると BLOCKER/WARNING の数と確定可否が変わります。</p></div>' +
    '<label class="field field--inline" style="margin-top:.6rem">' +
    '<span class="field__label">この園で採用する上限</span>' +
    '<select id="gate-select">' +
    '<option value="10"' + (state.gate === '10' ? ' selected' : '') + '>10時間（法定上限で止める）</option>' +
    '<option value="8.75"' + (state.gate === '8.75' ? ' selected' : '') + '>8時間45分（法定上限より厳しい）</option>' +
    '<option value="off"' + (state.gate === 'off' ? ' selected' : '') + '>判定しない（参考値のみ）</option>' +
    '</select></label>' +
    '<div class="summary" style="margin-top:.8rem">' +
    '<div class="stat"><p class="stat__label">採用した上限</p><p class="stat__value" style="font-size:1.1rem">' +
    esc(gateLabel) + '</p><p class="stat__note">' + esc(gateT.rule.label) + '</p></div>' +
    '<div class="stat"><p class="stat__label">この上限でBLOCKERになる人</p>' +
    '<p class="stat__value' + (monthBlockers ? ' stat__value--danger' : ' stat__value--ok') + '">' +
    monthBlockers + '</p><p class="stat__note">BLOCKER があると確定できません</p></div>' +
    '<div class="stat"><p class="stat__label">この上限でWARNINGになる人</p>' +
    '<p class="stat__value' + (monthWarnings ? ' stat__value--warn' : ' stat__value--ok') + '">' +
    monthWarnings + '</p><p class="stat__note">参考表示。確定は妨げません</p></div>' +
    '<div class="stat"><p class="stat__label">10時間を超える人</p>' +
    '<p class="stat__value' + (tally.over10.length ? ' stat__value--danger' : ' stat__value--ok') + '">' +
    tally.over10.length + '</p><p class="stat__note">ハード制約違反</p></div>' +
    '<div class="stat"><p class="stat__label">8時間45分〜10時間の帯域</p>' +
    '<p class="stat__value' + (tally.band.length ? ' stat__value--warn' : ' stat__value--ok') + '">' +
    tally.band.length + '</p><p class="stat__note">上限の選択により扱いが変わる人</p></div>' +
    '<div class="stat"><p class="stat__label">配置対象の職員</p><p class="stat__value">' + tally.total + '</p>' +
    '<p class="stat__note">引継時間を除いた実働</p></div>' +
    '</div>' +
    (tally.band.length
      ? '<details class="fold" style="margin-top:.4rem"><summary>帯域にいる職員（' + tally.band.length + '名）を表示</summary>' +
        '<div class="table-wrap" style="margin-top:.4rem"><table class="grid-table"><thead><tr>' +
        '<th>職員</th><th>その日の実働時間</th><th>10時間で止める場合</th><th>8時間45分で止める場合</th>' +
        '</tr></thead><tbody>' +
        tally.band.map(function (r) {
          return '<tr><td>' + esc(r.name) + '</td><td><strong>' + r.hours.toFixed(2) + 'h</strong></td>' +
            '<td>そのまま勤務できる</td><td style="color:var(--danger);font-weight:700">超過・配置し直しが必要</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="basis-text">この' + tally.band.length +
        '名は、上限を10時間にするとそのまま勤務できます（WARNING）。' +
        '8時間45分にすると BLOCKER となり、この職員を含むシフトは確定できなくなります。' +
        '2026-10-03 の決定は 10時間 を採用したものです。</p></details>'
      : '<p style="font-size:.82rem;color:var(--ink-2);margin-top:.6rem">' +
        'この日は帯域にいる職員がいません。上限の選択は結果に影響しません。</p>') +
    monthTallyHtml() +
    '</div>';

  /* --- gap --- */
  html += '<div class="card"><h2 class="card__title">人手不足</h2>' +
    (gaps.length
      ? '<div class="table-wrap"><table class="grid-table"><thead><tr>' +
        '<th>日付</th><th>時間帯</th><th>必要</th><th>供給</th><th>不足</th><th>種別</th>' +
        '</tr></thead><tbody>' +
        gaps.map(function (g) {
          return '<tr><td>' + esc(g.day) + '（' + weekdayOf(g.day) + '）</td><td>' + esc(g.slot) + '</td>' +
            '<td>' + g.need + '</td><td>' + g.supply + '</td>' +
            '<td style="color:var(--danger);font-weight:700">' + g.gap + '</td><td>' + esc(g.kind) + '</td></tr>';
        }).join('') + '</tbody></table></div>'
      : '<p style="font-size:.85rem;margin:0;color:var(--ink-2)">供給が需要を下回る時間帯はありません。</p>') +
    '</div>';

  /* --- violations --- */
  html += '<div class="card"><h2 class="card__title">法令・契約の判定（21種類）</h2>' +
    '<div class="table-wrap"><table class="grid-table"><thead><tr>' +
    '<th>区分</th><th>コード</th><th>日付</th><th>時間帯</th><th>対象</th><th>内容</th>' +
    '</tr></thead><tbody>' +
    violations.map(function (v) {
      const cls = v.severity === 'BLOCKER' ? 'danger' : (v.severity === 'WARNING' ? 'warn' : 'muted');
      return '<tr><td><span class="badge badge--' + cls + '">' + esc(v.severity) + '</span></td>' +
        '<td>' + esc(v.code) + '</td><td>' + esc(v.day) + '</td><td>' + esc(v.slot || '—') + '</td>' +
        '<td>' + esc(v.staff || '—') + '</td><td>' + esc(v.message) + '</td></tr>';
    }).join('') + '</tbody></table></div>' +
    '<p style="font-size:.78rem;color:var(--muted);margin:.6rem 0 0">' +
    'BLOCKER がある場合は承認できません。WARNING は確認の上、園の判断で進めます。</p>' +
    '</div>';

  /* --- arrival fallback notice (open item #4) --- */
  html += '<div class="card"><h2 class="card__title">登園予定時刻の補完</h2>' +
    '<div class="note note--warn"><p style="margin:0 0 .35rem">' +
    '在園 ' + CHILD_COUNT.total + ' 名のうち <strong>約 ' +
    Math.max(0, CHILD_COUNT.total - CHILD_COUNT.early - CHILD_COUNT.late) +
    ' 名</strong>の登園予定が未設定のため、保育標準時間（' +
    '08:30）から補完しました。園児ごとの既定値を設定すると、この補完は減ります。</p>' +
    '<p style="margin:0;font-size:.78rem">優先度: 実績打刻 → その日の上書き → 園児ごとの既定 → ' +
    '保育必要量の標準時間 → 開園時刻</p></div>' +
    '<p style="font-size:.78rem;color:var(--muted);margin:.6rem 0 0">' +
    '（園児ごとの既定値画面は今回のモック範囲外です）</p></div>';

  /* --- 次の操作（業務ルール 2026-10-03: 園長の承認で確定） --- */
  const canApprove = state.viewer.principal;
  html += '<div class="card"><h2 class="card__title">次の操作</h2>' +
    '<div class="row" style="margin-bottom:.7rem">' +
    '<label class="field field--inline"><span class="field__label">ログインしている人</span>' +
    '<select id="viewer-select" class="mock-input">' +
    '<option value="principal"' + (canApprove ? ' selected' : '') + '>桐生 園長（園長）</option>' +
    '<option value="staff"' + (canApprove ? '' : ' selected') + '>早乙女 主任（一般職員）</option>' +
    '</select></label>' +
    '<span class="toolbar__note">' +
    (canApprove
      ? '園長なので、このシフト案を確定できます'
      : '園長ではないため、確定できません（作成・編集はできます）') +
    '</span></div>' +
    '<div class="actions">' +
    '<button type="button" class="btn btn--primary" id="approve"' +
    (hasBlocker || !canApprove ? ' disabled' : '') + '>' +
    (canApprove ? 'この内容で確定する（園長の承認）' : '確定する（園長のみ）') + '</button>' +
    '<button type="button" class="btn btn--ghost" id="rerun">配置基準を変えて生成し直す</button>' +
    '<button type="button" class="btn btn--ghost" id="export">Excel に出力する</button>' +
    '</div>' +
    (hasBlocker
      ? '<p style="font-size:.82rem;color:var(--danger);margin:.7rem 0 0">' +
        'BLOCKER があるため、園長でも確定できません。</p>'
      : !canApprove
        ? '<p style="font-size:.82rem;color:var(--warn);margin:.7rem 0 0">' +
          'BLOCKER はないけども、確定できるのは園長だけです。上の「ログインしている人」を' +
          '園長に切り替えて確認できます。</p>'
        : '') +
    '<p style="font-size:.78rem;color:var(--muted);margin:.6rem 0 0">' +
    '確定は「下書き」を「確定済み」に変えるだけです。勤務実績（打刻）への反映は行いません。' +
    'シフト表の手動修正は次の段階のモックで対象です。</p></div>';

  body.innerHTML = html;
  renderShiftGrid();
}

/* --- 月次の時間外労働日数（業務ルール 2026-10-03） --- */
function monthTallyHtml() {
  const t = monthBandTally();
  const g = gateSeverity(t, state.gate);
  const gateDayLabel = { '10': '1日10時間超', '8.75': '1日8時間45分超', 'off': 'この上限で超える人' }[state.gate];
  return '<div class="card" id="month-tally"><h2 class="card__title">' +
    '月次の時間外労働日数（' + t.month + '）</h2>' +
    '<div class="note note--warn"><p style="margin:0 0 .4rem">' +
    '<strong>時間外労働は現在「案」の段階です。</strong>計算上は<strong>毎日発生する前提</strong>で' +
    '処理しています。そのため、この月間は<strong>勤務日数すべて</strong>を時間外労働日数として' +
    '数えており、' + OVERTIME_MONTH_CAP + '日・' + OVERTIME_YEAR_CAP + '年の枠を' +
    '大きく超えます。超過は<strong>参考表示のみ</strong>で、確定を止めません。' +
    '実際に時間外労働を入れた段階で、枠を BLOCKER にするかが変わります。</p></div>' +
    '<div class="summary" style="margin-top:.8rem">' +
    '<div class="stat"><p class="stat__label">対象月</p><p class="stat__value" style="font-size:1.1rem">' +
    esc(t.month) + '</p><p class="stat__note">' + t.days + '日（休園 ' + t.closed + '日）</p></div>' +
    '<div class="stat"><p class="stat__label">枠を超えた職員</p>' +
    '<p class="stat__value' + (t.overCap.length ? ' stat__value--warn' : ' stat__value--ok') + '">' +
    t.overCap.length + '</p><p class="stat__note">' + OVERTIME_MONTH_CAP + '日/月・' +
    OVERTIME_YEAR_CAP + '日/年（参考）</p></div>' +
    '<div class="stat"><p class="stat__label">' + esc(gateDayLabel) + '</p>' +
    '<p class="stat__value' + (g.blockers.length ? ' stat__value--danger' : ' stat__value--ok') + '">' +
    g.blockers.length + '</p><p class="stat__note">' + (state.gate === 'off' ? 'BLOCKER になりません' : 'BLOCKER になる') + '</p></div>' +
    '<div class="stat"><p class="stat__label">この上限でWARNINGになる人</p>' +
    '<p class="stat__value' + (g.warnings.length ? ' stat__value--warn' : ' stat__value--ok') + '">' +
    g.warnings.length + '</p><p class="stat__note">確定は妨げません</p></div>' +
    '<div class="stat"><p class="stat__label">配置対象の職員</p><p class="stat__value">' + t.rows.length +
    '</p><p class="stat__note">日次判定は毎日実施</p></div>' +
    '</div>' +
    '<details class="fold" open><summary>職員ごとの日数（' + t.rows.length + '名）</summary>' +
    '<div class="table-wrap" style="margin-top:.4rem"><table class="grid-table"><thead><tr>' +
    '<th>職員</th><th>勤務日数</th><th>時間外労働と数える日</th><th>枠の超過分</th>' +
    '<th>1日8時間45分超</th><th>1日10時間超</th>' +
    '</tr></thead><tbody>' +
    t.rows.map(function (r) {
      return '<tr><td>' + esc(r.name) + '</td><td>' + r.worked + '</td>' +
        '<td><strong>' + r.assumedDays + '</strong></td>' +
        '<td' + (r.overCap ? ' class="stat__value--warn"' : '') + '>+' + r.overCap + '</td>' +
        '<td>' + r.band + '</td>' +
        '<td' + (r.over10 ? ' style="color:var(--danger);font-weight:700"' : '') + '>' + r.over10 + '</td></tr>';
    }).join('') + '</tbody></table></div>' +
    '<p class="basis-text">この前提は「時間外労働が毎日発生する」を仮定した{' +
    '想定値であって、実績ではありません。実際の出勤記録からの集計は次のフェーズで' +
    '追加します。確定を止めるのは<strong>採用した上限（' + esc(g.rule.label) + '）</strong>だけです。</p></details>' +
    '</div>';
}

function renderShiftGrid() {
  const body = $('#shift-body');
  if (!body) { return; }
  body.innerHTML = buildGrid(state.selectedDay).map(function (r) {
    return '<tr><th>' + esc(r.name) + '<br><span style="font-weight:400;color:var(--muted);font-size:.68rem">' +
      esc(r.primary) + '</span></th>' +
      r.cells.map(function (c) {
        return '<td class="shift-cell shift-cell--' + c + '"></td>';
      }).join('') + '</tr>';
  }).join('');
}

/* ============================ イベント ============================ */
function bind() {
  $('#mock-state').addEventListener('change', function (e) {
    state.mock[state.view] = e.target.value;
    renderView();
    renderCurrent();
  });
  $('#mock-view').addEventListener('change', function (e) {
    state.view = e.target.value;
    renderView();
    renderCurrent();
  });
  $('#mock-reset').addEventListener('click', function () {
    state.staff = staffVariant(state.mock.contracts);
    state.staffSaved = staffVariant(state.mock.contracts);
    renderCurrent();
  });

  /* arrival */
  $('#arrival-day').addEventListener('change', function (e) {
    state.arrivalDay = e.target.value || '2026-11-04';
    renderArrivalSummary();
    renderArrivalTable();
  });
  $('#arrival-filter').addEventListener('change', function (e) {
    state.arrivalFilter = e.target.value;
    renderArrivalTable();
  });
  $('#arrival-body').addEventListener('change', function (e) {
    if (e.target.getAttribute('data-f') !== 'planned') { return; }
    const id = e.target.closest('tr').getAttribute('data-child');
    const c = state.children.filter(function (x) { return x.id === id; })[0];
    if (!c) { return; }
    c.planned = e.target.value;
    c.needDefault = !!e.target.value;
    renderArrival();
  });
  $('#arrival-save').addEventListener('click', function () {
    const probs = state.children.reduce(function (n, c) { return n + childProblems(c).length; }, 0);
    if (probs) {
      $('#arrival-msg').innerHTML = '<p class="msg msg--danger"><strong>保存できません。</strong>' +
        '不備のある園児が ' + probs + ' 件あります。</p>';
      return;
    }
    state.childrenSaved = state.children.map(function (c) { return Object.assign({}, c); });
    $('#arrival-msg').innerHTML =
      '<p class="msg msg--ok">保存しました（このモックでは画面内のメモのみです）。</p>';
  });
  $('#arrival-reset').addEventListener('click', function () {
    state.children = state.childrenSaved.map(function (c) { return Object.assign({}, c); });
    renderArrival();
  });
  $('#override-body').addEventListener('click', function (e) {
    const btn = e.target.closest('[data-remove-ov]');
    if (!btn) { return; }
    state.overrides.splice(parseInt(btn.getAttribute('data-remove-ov'), 10), 1);
    renderArrival();
  });
  $('#override-add').addEventListener('click', function () {
    const first = state.children[0];
    state.overrides.push({
      child: first.id, date: state.arrivalDay, planned: '09:00', reason: 'その他',
    });
    renderArrival();
  });

  /* facility */
  $('#facility-form').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const problems = validateFacility(false);
    if (problems.length) { return; }
    state.facility = {
      day_open: form.day_open.value, day_close: form.day_close.value,
      granularity_min: form.granularity_min.value, capacity: form.capacity.value,
      staffing_standard_key: form.staffing_standard_key.value,
      enforce_min_two: form.enforce_min_two.checked,
      time_limit_sec: form.time_limit_sec.value, relax_level: form.relax_level.value,
      closed_days: state.facility.closed_days.map(function (d) { return Object.assign({}, d); }),
    };
    state.facilitySaved = JSON.parse(JSON.stringify(state.facility));
    $('#facility-msg').innerHTML = '<p class="msg msg--ok">保存しました（このモックでは画面内のメモのみです）。</p>';
    $('#facility-state').innerHTML = '';
    facilityAudit();
  });
  $('#facility-cancel').addEventListener('click', function () {
    loadFacility(state.mock.facility);
    $('#facility-msg').innerHTML = '<p class="msg msg--warn">変更を破棄し、保存済みの値に戻しました。</p>';
    facilityAudit();
  });
  $('#standard-select').addEventListener('change', renderStandardNote);
  $('#closed-day-add').addEventListener('click', function () {
    const d = $('#closed-day-date').value;
    const k = $('#closed-day-kind').value;
    if (!d) { return; }
    if (state.facility.closed_days.some(function (x) { return x.date === d; })) { return; }
    state.facility.closed_days.push({ date: d, kind: k, label: k === 'closed' ? '休園日' : '祝日' });
    renderClosedDays();
  });
  $('#closed-day-list').addEventListener('click', function (e) {
    const t = e.target.closest('[data-remove-day]');
    if (!t) { return; }
    state.facility.closed_days.splice(parseInt(t.dataset.removeDay, 10), 1);
    renderClosedDays();
  });

  /* contracts */
  $('#contracts-body').addEventListener('change', function (e) {
    const cell = e.target.closest('[data-f]');
    if (!cell) { return; }
    const tr = cell.closest('tr');
    const s = state.staff.filter(function (x) { return x.id === tr.dataset.staff; })[0];
    s[cell.dataset.f] = cell.value;
    renderContracts();
  });
  $('#contracts-filter').addEventListener('change', renderContracts);
  $('#contracts-save').addEventListener('click', function () {
    const bad = state.staff.filter(function (s) {
      return NOT_PLACEABLE.indexOf(s.primary) < 0 && staffProblems(s).length > 0;
    });
    if (bad.length) {
      $('#contracts-msg').className = 'msg msg--danger';
      $('#contracts-msg').innerHTML = '保存できません。未入力の項目がある職員: ' +
        bad.map(function (s) { return esc(s.name) + '（' + staffProblems(s).join('、') + '）'; }).join('、');
      return;
    }
    state.staffSaved = state.staff.map(function (s) { return Object.assign({}, s); });
    $('#contracts-msg').className = 'msg msg--ok';
    $('#contracts-msg').innerHTML = '保存しました（このモックでは画面内のメモのみです）。';
    renderContracts();
  });
  $('#contracts-reset').addEventListener('click', function () {
    state.staff = state.staffSaved.map(function (s) { return Object.assign({}, s); });
    $('#contracts-msg').className = 'msg msg--warn';
    $('#contracts-msg').innerHTML = '未保存の変更を戻しました。';
    renderContracts();
  });
  $('#contracts-csv').addEventListener('click', function () {
    $('#contracts-msg').className = 'msg msg--warn';
    $('#contracts-msg').innerHTML =
      'CSV取り込みを選ぶ場合の画面は未実装です。フォーム一括と取り込みのどちらがよいかを確認しています（未確定事項6）。';
  });

  /* generate */
  $('#generate-form').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    if (form.target_month.value) { state.generate.target_month = form.target_month.value; }
    if (form.staffing_standard_key.value) { state.generate.staffing_standard_key = form.staffing_standard_key.value; }
    const p = preconditions();
    if (p.length) {
      $('#generate-msg').innerHTML = '<p class="msg msg--danger"><strong>生成できません。</strong><br>' +
        p.map(esc).join('<br>') + '</p>';
      return;
    }
    runProgress(form);
  });
  $('#generate-cancel').addEventListener('click', function () {
    form_reset($('#generate-form'));
    $('#generate-progress').innerHTML = '';
    $('#generate-msg').innerHTML = '<p class="msg msg--warn">入力を元に戻しました。</p>';
    $('#generate-run').disabled = false;
  });

  /* result */
  document.addEventListener('change', function (e) {
    if (e.target.id === 'gate-select') {
      state.gate = e.target.value;
      renderResult(state.mock.result);
      return;
    }
    if (e.target.id === 'viewer-select') {
      state.viewer.principal = e.target.value === 'principal';
      renderResult(state.mock.result);
    }
  });
  document.addEventListener('click', function (e) {
    const day = e.target.closest('[data-day]');
    if (day) {
      state.selectedDay = day.dataset.day;
      $$('#day-tabs .day-tab').forEach(function (b) {
        b.classList.toggle('is-active', b.dataset.day === state.selectedDay);
      });
      renderShiftGrid();
      return;
    }
    const nav = e.target.closest('[data-nav]');
    if (nav) {
      state.view = nav.dataset.nav;
      renderView();
      renderCurrent();
      return;
    }
    if (e.target.id === 'approve') {
      const box = document.createElement('p');
      box.className = 'msg msg--ok';
      box.textContent = '下書きを確定状態にしました（このモックでは保存されません）。勤務実績には反映されません。';
      e.target.closest('.card').appendChild(box);
      return;
    }
    if (e.target.id === 'rerun') {
      state.view = 'generate';
      state.mock.generate = 'ready';
      renderView();
      renderCurrent();
      return;
    }
    if (e.target.id === 'export') {
      const box = document.createElement('p');
      box.className = 'msg msg--warn';
      box.textContent = '出力は行いません（このモックではファイルを作りません）。';
      e.target.closest('.card').appendChild(box);
    }
  });
}

function form_reset(form) {
  form.reset();
  $('#generate-standard').value = state.generate.staffing_standard_key || '';
}

/* ======================= 画面1 登園予定時刻 ======================= */
function arrivalCtx() {
  return {
    overrides: state.overrides,
    dayOpen: (state.facilitySaved && state.facilitySaved.day_open) || '07:30',
    dayClose: (state.facilitySaved && state.facilitySaved.day_close) || '19:30',
    today: '2026-10-03',
  };
}

function childProblems(c) {
  const ctx = arrivalCtx();
  const p = [];
  const t = c.planned;
  if (t && !/^\d{2}:\d{2}$/.test(t)) {
    p.push('既定の登園予定は「HH:MM」形式で入力してください（現在: ' + t + '）');
  } else if (t && t >= ctx.dayClose) {
    p.push('既定の登園予定が閉園時刻（' + ctx.dayClose + '）以降です');
  } else if (t && t < ctx.dayOpen) {
    p.push('既定の登園予定が開園時刻（' + ctx.dayOpen + '）より前です');
  }
  return p;
}

function overrideProblems() {
  const ctx = arrivalCtx();
  const out = [];
  state.overrides.forEach(function (o) {
    const when = o.date + ' ' + o.child;
    if (!/^\d{2}:\d{2}$/.test(o.planned)) {
      out.push(when + ' の登園予定は「HH:MM」形式ではありません（現在: ' + o.planned + '）');
    } else if (o.planned >= ctx.dayClose) {
      out.push(when + ' の登園予定が閉園時刻（' + ctx.dayClose + '）以降です');
    }
    if (o.date.slice(0, 7) !== TARGET_MONTH) {
      out.push(when + ' は対象月（' + TARGET_MONTH + '）の外です');
    }
  });
  return out;
}

function renderArrivalSummary() {
  const ctx = arrivalCtx();
  $('#arrival-day').value = state.arrivalDay;
  const byLevel = {};
  state.children.forEach(function (c) {
    const r = resolveArrival(c, state.arrivalDay, ctx);
    byLevel[r.level] = (byLevel[r.level] || 0) + 1;
  });
  const labels = { 1: '実績打刻', 2: 'その日の上書き', 3: '園児ごとの既定値', 4: '保育必要量区分', 5: '開園時刻' };
  const notes = {
    1: '対象日が今日より前',
    2: '例外日で上書き',
    3: '園児ごとに設定',
    4: '既定値なし。区間の開始時刻に落ちています',
    5: '区分もなし。開園時刻まで落ちています',
  };
  $('#arrival-summary').innerHTML = [1, 2, 3, 4, 5].map(function (lv) {
    const n = byLevel[lv] || 0;
    const cls = lv <= 3 ? 'stat__value--ok' : (lv === 4 ? 'stat__value--warn' : 'stat__value--danger');
    return '<div class="stat"><p class="stat__label">' + labels[lv] + '</p>' +
      '<p class="stat__value ' + cls + '">' + n + '名</p>' +
      '<p class="stat__note">' + notes[lv] + '</p></div>';
  }).join('') +
    '<div class="stat"><p class="stat__label">確認する日</p>' +
    '<p class="stat__value" style="font-size:1.1rem">' + esc(state.arrivalDay) + '</p>' +
    '<p class="stat__note">この日换来ると補完元も変わります</p></div>';
}

function renderArrivalTable() {
  const ctx = arrivalCtx();
  const rows = state.children.filter(function (c) {
    if (state.arrivalFilter === 'unset') { return !c.planned; }
    if (state.arrivalFilter === 'set') { return !!c.planned; }
    return true;
  });
  $('#arrival-count').textContent = rows.length + '名 / 全' + state.children.length + '名';
  $('#arrival-body').innerHTML = rows.map(function (c) {
    const r = resolveArrival(c, state.arrivalDay, ctx);
    const p = childProblems(c);
    const badge = r.level <= 3 ? 'badge--ok' : (r.level === 4 ? 'badge--warn' : 'badge--danger');
    return '<tr class="' + (p.length ? 'is-missing' : '') + '" data-child="' + esc(c.id) + '">' +
      '<td><strong>' + esc(c.name) + '</strong><br><span style="color:var(--muted);font-size:.78rem">' +
      esc(c.id) + '</span></td>' +
      '<td>' + esc(c.categoryName) + '</td>' +
      '<td><input type="time" class="mock-input" data-f="planned" value="' + esc(c.planned) + '"></td>' +
      '<td>' + esc(c.categoryStart) + '</td>' +
      '<td>' + (p.length
        ? '<span class="badge badge--danger">入力に不備あり</span><br>' +
          '<span style="color:var(--danger);font-weight:700">' + esc(c.planned) + '</strong></span><br>' +
          '<span style="color:var(--muted);font-size:.78rem">保存できません。' +
          esc(p[0]) + '</span>'
        : '<span class="badge ' + badge + '">' + esc(r.at) + '</span><br>' +
          '<strong>' + esc(r.time) + '</strong><br>' +
          '<span style="color:var(--muted);font-size:.78rem">' + esc(r.why) + '</span>') + '</td></tr>';
  }).join('');
}

function renderOverrides() {
  $('#override-body').innerHTML = state.overrides.length
    ? state.overrides.map(function (o, i) {
      const c = state.children.filter(function (x) { return x.id === o.child; })[0];
      const bad = overrideProblems().some(function (m) { return m.indexOf(o.date + ' ' + o.child) >= 0; });
      return '<tr class="' + (bad ? 'is-missing' : '') + '" data-ov="' + i + '">' +
        '<td>' + esc(c ? c.name : o.child) + '</td>' +
        '<td>' + esc(o.date) + '</td>' +
        '<td><input type="time" class="mock-input" data-f="planned" value="' + esc(o.planned) + '"></td>' +
        '<td>' + esc(o.reason) + '</td>' +
        '<td><button type="button" class="btn btn--ghost" data-remove-ov="' + i + '">削除</button></td></tr>';
    }).join('')
    : '<tr><td colspan="5" style="color:var(--muted)">例外日の登録はありません。' +
      '登録がない日は園児ごとの既定値を使います。</td></tr>';
}

function renderArrival() {
  renderArrivalSummary();
  renderArrivalTable();
  renderOverrides();
  const childMsgs = state.children.reduce(function (acc, c) {
    return acc.concat(childProblems(c).map(function (m) { return c.name + ': ' + m; }));
  }, []);
  const probs = childMsgs.concat(overrideProblems());
  $('#arrival-msg').innerHTML = probs.length
    ? '<p class="msg msg--danger"><strong>保存できません。</strong><br>' +
      probs.map(esc).join('<br>') + '</p>'
    : '';
}

function renderCurrent() {
  const v = state.view;
  const m = state.mock[v];
  if (v === 'arrival') { state.children = childVariant(m); state.overrides = overridesVariant(m); renderArrival(); return; }
  if (v === 'facility') { loadFacility(m); facilityAudit(); return; }
  if (v === 'contracts') { state.staff = staffVariant(m); renderContracts(); return; }
  if (v === 'generate') { loadGenerate(m); renderGenerateErrors(m); return; }
  if (v === 'result') { renderResult(m); return; }
}

document.addEventListener('DOMContentLoaded', function () {
  bind();
  renderView();
  renderCurrent();
});
