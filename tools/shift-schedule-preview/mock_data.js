/* Fictional data for the shift-schedule confirmation mock.
 *
 * Sourced from the real enumerations in E:\nushift\nushift\src\shiftai:
 *   domain.py:22-55   AgeClass
 *   domain.py:58-68   Role
 *   domain.py:71-83   EmploymentType / COST_COEFFICIENT
 *   local_rules.py:172-511  the 14 staffing-standard presets
 *
 * Every person, child count, and shift below is invented. No production data.
 */
'use strict';

const STANDARDS = [
  { key: '全国基準（厚労省）', name: '全国基準（厚労省）',
    summary: '3/6/6/8/20/20 を定員比で切り上げ。保育標準時間の基準に揃える園の初期値',
    source: '保育所の職員配置基準（昭和52年厚生省告示第49号）' },
  { key: '東京都', name: '東京都', summary: '3/6/6/8/12/12。延長保育の緩和措置あり',
    source: '東京都保育所の職員配置基準' },
  { key: '横浜市', name: '横浜市', summary: '3/6/6/8/12/12。延長保育の緩和措置あり', source: '横浜市保育所の職員配置基準' },
  { key: '大阪市', name: '大阪市', summary: '4/5/7/8/12/12。0歳の定員比が厳しい', source: '大阪市保育所の職員配置基準' },
  { key: '福岡市', name: '福岡市', summary: '3/4/6/8/12/12。1歳の定員比が厳しい', source: '福岡市保育所の職員配置基準' },
  { key: '名古屋市', name: '名古屋市', summary: '3/6/6/8/20/20', source: '名古屋市保育所の職員配置基準' },
  { key: '京都市', name: '京都市', summary: '3/6/6/8/20/20', source: '京都市保育所の職員配置基準' },
  { key: '札幌市', name: '札幌市', summary: '3/6/6/8/20/20。延長保育の緩和措置なし', source: '札幌市保育所の職員配置基準' },
  { key: '神戸市', name: '神戸市', summary: '3/6/6/8/12/12', source: '神戸市保育所の職員配置基準' },
  { key: '川崎市', name: '川崎市', summary: '3/6/6/8/12/12', source: '川崎市保育所の職員配置基準' },
  { key: '保育標準時間のみ園', name: '保育標準時間のみ園',
    summary: '短時間保育の園向け。延長保育の時間帯を計算対象外にする', source: '保育標準時間のみを保育する園の運用' },
  { key: '認可外保育施設（指導監督基準）', name: '認可外保育施設（指導監督基準）',
    summary: '3/6/6/20/30/30。施設全体の定員で必要人数を計算する',
    source: '認可外保育施設指導監督基準（令和6年3月29日こ成保第206号）第1' },
  { key: '企業主導型保育事業（単独枠）', name: '企業主導型保育事業（単独枠）',
    summary: '3/6/6/20/30/30。資格要件0.5人',
    source: '企業主導型保育事業費補助金実施要綱 第3の2(4)①' },
  { key: '企業主導型保育事業（保育事業者型・20名以上）', name: '企業主導型保育事業（保育事業者型・20名以上）',
    summary: '3/6/6/20/30/30。資格要件0.75人',
    source: '企業主導型保育事業費補助金実施要綱 第3の2(4)②' },
];

const ROLES = ['保育士', '子育て支援員', '幼稚園教諭', '看護師', '栄養教諭', '調理員', '薬剤師', '園長・主任（配置対象外）'];
const EMPLOYMENT = [
  { name: '正職員', coefficient: 1.25 },
  { name: '契約社員', coefficient: 1.15 },
  { name: 'パート', coefficient: 1.0 },
  { name: 'アルバイト', coefficient: 1.0 },
];
/* domain.py is_placeable excludes these four from shift slots. */
const NOT_PLACEABLE = ['栄養教諭', '調理員', '薬剤師', '園長・主任（配置対象外）'];

const FACILITY_DEFAULT = {
  day_open: '07:30', day_close: '19:30', granularity_min: '30', capacity: '60',
  staffing_standard_key: '福岡市', enforce_min_two: true,
  time_limit_sec: '30', relax_level: '0',
  closed_days: [
    { date: '2026-11-03', kind: 'holiday', label: '文化の日' },
    { date: '2026-11-23', kind: 'holiday', label: '勤労感謝の日' },
    { date: '2026-11-28', kind: 'closed', label: '園研修' },
  ],
};

const FACILITY_EMPTY = {
  day_open: '', day_close: '', granularity_min: '30', capacity: '',
  staffing_standard_key: '', enforce_min_two: true,
  time_limit_sec: '', relax_level: '0', closed_days: [],
};

const FACILITY_PARTIAL = Object.assign({}, FACILITY_DEFAULT, {
  day_close: '', capacity: '', staffing_standard_key: '全国基準（厚労省）',
});

const FACILITY_INVALID = Object.assign({}, FACILITY_DEFAULT, {
  day_open: '19:30', day_close: '07:30',
});

/* --- staff ---------------------------------------------------------------
 * weekly_hours / daily_hours / max_weekly_days / max_consecutive_days /
 * earliest_start / latest_end map to shiftai Contract (domain.py:306-325).
 */
const STAFF_ALL = [
  /* --- 配置対象外（shiftai の is_placeable が除外する職種） --- */
  { id: 'S-01', name: '桐生 園長',   primary: '園長・主任（配置対象外）', secondary: '',            employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '18:00' },
  { id: 'S-09', name: '天野 栞',     primary: '栄養教諭',                secondary: '',            employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '17:00' },
  { id: 'S-10', name: '宮原 うめ',   primary: '調理員',                  secondary: '',            employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '09:00', latest: '16:00' },
  { id: 'S-29', name: '芦田 幸子',   primary: '調理員',                  secondary: '',            employment: 'パート', weekly: '15', daily: '4', maxDays: '3', maxConsec: '3', earliest: '09:00', latest: '16:00' },
  { id: 'S-30', name: '伏見 凉',     primary: '薬剤師',                  secondary: '',            employment: 'アルバイト', weekly: '6', daily: '3', maxDays: '2', maxConsec: '2', earliest: '09:00', latest: '15:00' },

  /* --- 正職員 保育士・主任 --- */
  { id: 'S-02', name: '早乙女 主任', primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '07:00', latest: '19:00' },
  { id: 'S-03', name: '三島 慧',     primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '07:00', latest: '19:00' },
  { id: 'S-04', name: '篠原 菜々',   primary: '保育士', secondary: '子育て支援員',           employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '18:00' },
  { id: 'S-11', name: '神谷 灯',     primary: '幼稚園教諭', secondary: '',                  employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '18:00' },
  { id: 'S-12', name: '和泉 紗英',   primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '07:30', latest: '18:30' },
  { id: 'S-13', name: '瀬能 枫',     primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '17:30' },
  { id: 'S-14', name: '香月 直人',   primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '09:00', latest: '18:00' },
  { id: 'S-15', name: '宮下 澪',     primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '07:30', latest: '18:00' },
  { id: 'S-16', name: '花城 佳穂',   primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '18:30' },
  { id: 'S-17', name: '青砥 桜',     primary: '保育士', secondary: '',                     employment: '正職員', weekly: '40', daily: '8', maxDays: '5', maxConsec: '5', earliest: '08:30', latest: '17:30' },

  /* --- 契約社員 --- */
  { id: 'S-18', name: '肥後 みのり', primary: '保育士', secondary: '',                     employment: '契約社員', weekly: '35', daily: '7', maxDays: '5', maxConsec: '5', earliest: '08:00', latest: '18:00' },
  { id: 'S-19', name: '高瀬 諒',     primary: '保育士', secondary: '',                     employment: '契約社員', weekly: '35', daily: '7', maxDays: '5', maxConsec: '4', earliest: '07:30', latest: '18:30' },

  /* --- パート 保育士 --- */
  { id: 'S-05', name: '西郷 大和',   primary: '保育士', secondary: '',                     employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '08:00', latest: '17:00' },
  { id: 'S-06', name: '平賀 あかり', primary: '保育士', secondary: '',                     employment: 'パート', weekly: '25', daily: '6', maxDays: '5', maxConsec: '4', earliest: '07:30', latest: '18:30' },
  { id: 'S-20', name: '二階堂 蓮',   primary: '保育士', secondary: '',                     employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '08:30', latest: '17:30' },
  { id: 'S-21', name: '真柴 遥',     primary: '保育士', secondary: '',                     employment: 'パート', weekly: '15', daily: '4', maxDays: '3', maxConsec: '2', earliest: '09:00', latest: '16:00' },
  { id: 'S-22', name: '鴨志田 鈴',   primary: '保育士', secondary: '',                     employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '07:30', latest: '18:00' },

  /* --- パート 子育て支援員 --- */
  { id: 'S-07', name: '小泉 みのり', primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '25', daily: '6', maxDays: '5', maxConsec: '4', earliest: '07:30', latest: '18:30' },
  { id: 'S-23', name: '伊東 志乃',   primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '08:00', latest: '17:00' },
  { id: 'S-24', name: '亀井 あき',   primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '07:30', latest: '18:30' },
  { id: 'S-25', name: '白井 里緒',   primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '15', daily: '4', maxDays: '3', maxConsec: '2', earliest: '09:00', latest: '16:00' },
  { id: 'S-26', name: '氷室 千代',   primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '20', daily: '5', maxDays: '4', maxConsec: '3', earliest: '08:00', latest: '18:00' },
  { id: 'S-27', name: '千秋 綾',     primary: '子育て支援員', secondary: '',              employment: 'パート', weekly: '15', daily: '4', maxDays: '3', maxConsec: '2', earliest: '08:30', latest: '16:30' },

  /* --- アルバイト 子育て支援員 --- */
  { id: 'S-28', name: '水無月 慧太', primary: '子育て支援員', secondary: '',              employment: 'アルバイト', weekly: '10', daily: '5', maxDays: '3', maxConsec: '2', earliest: '08:30', latest: '17:30' },

  /* --- 看護師 --- */
  { id: 'S-08', name: '伊達 千歳',   primary: '看護師', secondary: '',                     employment: 'パート', weekly: '12', daily: '6', maxDays: '3', maxConsec: '2', earliest: '09:00', latest: '15:00' },
];

/* 一部入力（未確定の画面数・状態）: 職員ID で指定するので、並び順に依存しない。
 * S-06 資格なし / S-21 時間未入力 / S-23 職務未入力 */
function staffVariantById(overrides) {
  return STAFF_ALL.map(function (s) {
    const patch = overrides[s.id];
    return patch ? Object.assign({}, s, patch) : Object.assign({}, s);
  });
}
const STAFF_PARTIAL = staffVariantById({
  'S-06': { primary: '', secondary: '' },
  'S-21': { weekly: '', daily: '' },
  'S-23': { employment: '' },
});

const STAFF_EMPTY = STAFF_ALL.map(function (s) {
  return Object.assign({}, s, {
    primary: '', secondary: '', employment: '', weekly: '', daily: '',
    maxDays: '', maxConsec: '', earliest: '', latest: '',
  });
});

/* エラー: 時間が0 / 始業終業が逆 / 資格なし */
const STAFF_INVALID = staffVariantById({
  'S-03': { weekly: '0', daily: '0' },
  'S-08': { earliest: '18:00', latest: '08:00' },
  'S-06': { primary: '', secondary: '' },
});

/* --- facility input summary shown on the generate screen ----------------- */
const CHILD_COUNT = { total: 62, standard: 41, short: 14, early: 5, late: 19 };

/* --- one day's requirement table (Requirements -> Requirement) -----------
 * basis mirrors the rationale string that shiftai attaches to every number.
 */
const REQUIREMENT_DAY = '2026-11-04';
const REQUIREMENT_ROWS = [
  { slot: '07:30-08:00', age: '0歳児', need: 1, basis: '0歳児 3名 ÷ 3 = 1名（定員比3:1、切り上げ）／保育標準時間／2名ルールによる底上げなし（0歳児のみ在園）' },
  { slot: '07:30-08:00', age: '1・2歳児', need: 2, basis: '1・2歳児 12名 ÷ 6 = 2名（定員比6:1、切り上げ）／保育標準時間／2名ルールによる底上げ' },
  { slot: '08:00-08:30', age: '0歳児', need: 1, basis: '0歳児 3名 ÷ 3 = 1名（定員比3:1、切り上げ）' },
  { slot: '08:00-08:30', age: '1・2歳児', need: 2, basis: '1・2歳児 15名 ÷ 6 = 3名 → 朝延長のみのため2名に抑制' },
  { slot: '08:30-11:00', age: '0歳児', need: 1, basis: '0歳児 4名 ÷ 3 = 2名 → 短時間保育児1名・2名ルールにより1名に抑制' },
  { slot: '08:30-11:00', age: '1・2歳児', need: 4, basis: '1・2歳児 22名 ÷ 6 = 4名（定員比6:1、切り上げ）' },
  { slot: '08:30-11:00', age: '3歳児', need: 3, basis: '3歳児 17名 ÷ 6 = 3名（定員比6:1、切り上げ）' },
  { slot: '08:30-11:00', age: '4・5歳児', need: 4, basis: '4・5歳児 19名 ÷ 12 = 2名 → 2名ルールによる底上げ' },
  { slot: '11:00-16:30', age: '0歳児', need: 1, basis: '0歳児 4名 ÷ 3 = 2名 → 短時間保育児1名・2名ルールにより1名に抑制' },
  { slot: '11:00-16:30', age: '1・2歳児', need: 4, basis: '1・2歳児 24名 ÷ 6 = 4名（定員比6:1、切り上げ）' },
  { slot: '11:00-16:30', age: '3歳児', need: 3, basis: '3歳児 17名 ÷ 6 = 3名（定員比6:1、切り上げ）' },
  { slot: '11:00-16:30', age: '4・5歳児', need: 2, basis: '4・5歳児 19名 ÷ 12 = 2名（定員比12:1、切り上げ）' },
  { slot: '16:30-18:00', age: '1・2歳児', need: 3, basis: '1・2歳児 19名 ÷ 6 = 4名 → 延長保育の緩和措置により3名' },
  { slot: '16:30-18:00', age: '3歳児', need: 2, basis: '3歳児 12名 ÷ 6 = 2名（定員比6:1、切り上げ）' },
  { slot: '16:30-18:00', age: '4・5歳児', need: 2, basis: '4・5歳児 14名 ÷ 12 = 2名（定員比12:1、切り上げ）' },
  { slot: '18:00-19:30', age: '全年齢', need: 2, basis: '延長保育 19名。延長保育（緩和措置なし）／2名ルールによる底上げ' },
];

/* --- one day's shift grid (SolveResult -> ShiftDay) --------------------- */
const SHIFT_DAYS = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06'];
const SLOTS = ['07:30', '08:00', '08:30', '09:00', '09:30', '10:00', '10:30', '11:00',
  '11:30', '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '15:00',
  '15:30', '16:00', '16:30', '17:00', '17:30', '18:00', '18:30', '19:00'];
const SLOT_KIND = SLOTS.map(function (s) {
  if (s < '08:30') return '早朝保育';
  if (s < '16:30') return '保育標準時間';
  return '延長保育';
});

/* --- one day's shift grid (SolveResult -> ShiftDay) ---------------------
 * Pattern is generated from each staff member's contract (earliest/latest/
 * max_weekly_days) rather than hard-coded, so it scales with the roster and
 * stays inside 労働基準法 10h. Cells are 30-minute slots.
 *   'work' 勤務 / 'off' 休み / 'blank' 未割当（人が足りない）
 */
const SLOT_MINUTES = 30;
const DAY_OPEN_MINUTES = 7 * 60 + 30;
const TARGET_MONTH = '2026-11';
const MONTH_LENGTH = 30;
/* 施設設定の休園日・祝日。SHIFT_DAYS の祝日と月次集計の双方で同じものを使う */
const CLOSED_DATES = ['2026-11-03', '2026-11-23', '2026-11-28'];

function isClosed(iso) { return CLOSED_DATES.indexOf(iso) >= 0; }

function pad2(n) { return n < 10 ? '0' + n : String(n); }

function monthDayDates() {
  const out = [];
  for (let d = 1; d <= MONTH_LENGTH; d += 1) { out.push(TARGET_MONTH + '-' + pad2(d)); }
  return out;
}

function slotIndexOf(hhmm) {
  if (!/^\d{2}:\d{2}$/.test(hhmm || '')) { return 0; }
  const h = parseInt(hhmm.slice(0, 2), 10);
  const m = parseInt(hhmm.slice(3, 5), 10);
  return Math.round((h * 60 + m - DAY_OPEN_MINUTES) / SLOT_MINUTES);
}

/* 「1日10時間超の例」用の上書き（BLOCKER を出す状態）
 * 通常は null。画面5 の状態=daily-long のときだけ 1 名の契約時間を伸ばす。 */
let LONG_DAY_OVERRIDE = null;

function setLongDay(on) {
  LONG_DAY_OVERRIDE = on ? { id: 'S-03', hours: 11 } : null;
}

function placeableStaff() {
  const list = STAFF_ALL.filter(function (s) { return NOT_PLACEABLE.indexOf(s.primary) < 0; });
  if (!LONG_DAY_OVERRIDE) { return list; }
  return list.map(function (s) {
    return s.id === LONG_DAY_OVERRIDE.id
      ? Object.assign({}, s, { daily: String(LONG_DAY_OVERRIDE.hours) })
      : s;
  });
}

function cellsFor(staff, i, dayIndex, closed) {
  const cells = new Array(SLOTS.length).fill('off');
  if (closed) { return cells; }
  const maxDays = parseInt(staff.maxDays || '5', 10) || 5;
  /* 5日勤務の職員でも、曜日によって休み落入を割り当てる */
  if (((i * 2) + dayIndex) % 7 >= maxDays) { return cells; }
  const es = Math.max(0, slotIndexOf(staff.earliest));
  const ls = Math.min(SLOTS.length, slotIndexOf(staff.latest) + 1);
  const span = Math.max(2, ls - es);
  /* 契約の1日勤務時間を基準に、6日に1日だけ時間外（+2時間）させる。
   * 幅は30分×20=10.0時間を超えないので、ハード制約10.0時間に収まる。 */
  const baseSlots = Math.max(4, Math.round((parseFloat(staff.daily) || 8) * 2));
  const extra = ((i * 5 + dayIndex) % 6 === 0) ? 4 : 0;
  const len = Math.min(span, baseSlots + extra);
  const slack = span - len;
  const off = slack > 0 ? ((i * 3 + dayIndex * 2) % slack) : 0;
  for (let k = 0; k < len; k += 1) { cells[es + off + k] = 'work'; }
  return cells;
}

function buildGrid(day) {
  const closed = isClosed(day);
  const dayIndex = Math.max(0, SHIFT_DAYS.indexOf(day));
  const rows = placeableStaff().map(function (s, i) {
    return {
      id: s.id, name: s.name, primary: s.primary, employment: s.employment,
      cells: cellsFor(s, i, dayIndex, closed),
    };
  });
  if (!closed) {
    /* 意図的に1マス未割当にして、人手的不足が結果に現れるようにする */
    const target = rows.filter(function (r) { return r.id === 'S-05'; })[0];
    if (target) {
      const lastWork = target.cells.lastIndexOf('work');
      if (lastWork >= 0) { target.cells[lastWork] = 'blank'; }
    }
  }
  return rows;
}

/* --- 1日の労働時間（未確定事項2 の帯域表示用） -----------------------
 * shiftai config.py:34-54 は意図的に4つの閾値を持つ。
 *   10.0  労働基準法32条・34条の1日上限（ハード制約）
 *   8.75  法定8h + 休憩45分（gap_analysis の適合判定）
 *   9.0   ソルバ内部のペナルチ目安（適合判定ではない）
 * ここでは生成されたシフトから実働時間を出し、上2つとの帯域別人数を数える。
 */
const DAILY_GATE_HARD_HOURS = 10.0;
const DAILY_GATE_ADVISORY_HOURS = 8.75;

/* 実働時間。shiftai exporter.py の payroll は休憩を引かない
 * （docs/07 T-05「人件費の基準を実働基準に統一」／docs/09 NG-01 で意図と確認済み）。
 * そのためここでも休憩を引かない。単位は時間、30分マスのまま。 */
function workedHoursFor(staff, i, dayIndex, closed) {
  const cells = cellsFor(staff, i, dayIndex, !!closed);
  const workSlots = cells.filter(function (c) { return c === 'work'; }).length;
  return Math.round((workSlots * SLOT_MINUTES) / 60 * 100) / 100;
}

function dailyHoursByStaff(day) {
  const dayIndex = Math.max(0, SHIFT_DAYS.indexOf(day));
  const closed = isClosed(day);
  return placeableStaff().map(function (s, i) {
    return { id: s.id, name: s.name, hours: workedHoursFor(s, i, dayIndex, closed) };
  });
}

function bandTally(day) {
  const rows = dailyHoursByStaff(day);
  return {
    rows: rows,
    total: rows.length,
    over10: rows.filter(function (r) { return r.hours > DAILY_GATE_HARD_HOURS; }),
    band: rows.filter(function (r) {
      return r.hours > DAILY_GATE_ADVISORY_HOURS && r.hours <= DAILY_GATE_HARD_HOURS;
    }),
  };
}

/* --- 未確定事項2: 採用する上限が承認判定にどう効くか --------------------
 * 業務ルール 2026-10-03 の決定:
 *   10時間超   = BLOCKER（労働基準法32条違反）
 *   8時間45分超 = WARNING（時間外労働・1.25倍）
 * 8時間45分を BLOCKER にすると正職員のほぼすべての日が確定できなくなるため採らない。
 * 'off' は参考表示のみとし、この規則による BLOCKER も WARNING も作らない。
 * 選択を変えるとBLOCKER/WARNING の数と確定可否が変わることを示すための表。
 */
const GATE_RULES = {
  '10': { hard: 'BLOCKER', band: 'WARNING', label: '10時間超＝BLOCKER／8時間45分超＝WARNING' },
  '8.75': { hard: 'BLOCKER', band: 'BLOCKER', label: '8時間45分超＝BLOCKER（法定上限10時間を無視）' },
  'off': { hard: null, band: null, label: '判定しない（参考値のみ）' },
};

/* 月次の集計を、採用する上限に応じて BLOCKER / WARNING に振り分ける。
 * gate は app.js の state.gate から渡す（このファイルは状態に依存しない）。 */
function gateSeverity(tally, gate) {
  const rule = GATE_RULES[gate] || GATE_RULES['10'];
  const rows = tally.rows || [];
  const blockers = [];
  const warnings = [];
  rows.forEach(function (r) {
    if (rule.hard && r.over10 > 0) {
      blockers.push({ staff: r, kind: 'over10', days: r.over10 });
    } else if (rule.band && r.band > 0) {
      (rule.band === 'BLOCKER' ? blockers : warnings).push({ staff: r, kind: 'band', days: r.band });
    }
  });
  return { rule: rule, blockers: blockers, warnings: warnings };
}

/* --- 月次の時間外労働日数（業務ルール 2026-10-03） -----------------
 * 時間外労働は現時点で「案」の段階。計算上は**毎日発生する前提**で処理する。
 * そのcip的结果、勤務日数はすべて時間外労働日数として数える。
 * 月5日・年6日の枠は**参考表示だけ**で、BLOCKER にもしない。
 * 「月初から既に使用した日数」の入力は設けない（実データが無いため）。
 */
const OVERTIME_MONTH_CAP = 5;
const OVERTIME_YEAR_CAP = 6;

function monthBandTally() {
  const days = monthDayDates();
  const rows = placeableStaff().map(function (s, i) {
    let band = 0, over10 = 0, worked = 0;
    days.forEach(function (d, di) {
      const h = workedHoursFor(s, i, di, isClosed(d));
      if (h > 0) { worked += 1; }
      if (h > DAILY_GATE_HARD_HOURS) { over10 += 1; }
      else if (h > DAILY_GATE_ADVISORY_HOURS) { band += 1; }
    });
    /* 「毎日発生する」前提なので、勤務日数すべてが枠を消費する */
    return {
      id: s.id, name: s.name, primary: s.primary,
      worked: worked, band: band, over10: over10,
      assumedDays: worked,
      overCap: Math.max(0, worked - OVERTIME_MONTH_CAP),
      severity: over10 > 0 ? 'BLOCKER' : 'OK',
    };
  });
  return {
    month: TARGET_MONTH,
    days: days.length,
    closed: CLOSED_DATES.length,
    rows: rows,
    overCap: rows.filter(function (r) { return r.overCap > 0; }),
    hardViolations: rows.filter(function (r) { return r.over10 > 0; }),
  };
}

/* --- supply gap ---------------------------------------------------------- */
const GAP_ROWS_OK = [];
const GAP_ROWS_SHORT = [
  { day: '2026-11-05', slot: '08:00-08:30', need: 2, supply: 1, gap: 1, kind: '職員数' },
  { day: '2026-11-05', slot: '16:30-17:00', need: 3, supply: 2, gap: 1, kind: '職員数' },
  { day: '2026-11-06', slot: '16:30-17:00', need: 3, supply: 2, gap: 1, kind: '保育士数' },
];

/* --- violations (gap_analysis.VIOLATION_CODE_LABELS, 21 codes) ----------- */
const VIOLATIONS_CLEAN = [
  { severity: 'INFO', code: 'FAIRNESS_SPREAD', day: '2026-11-04', slot: '', staff: '', message: '勤務時間の最大と最小の差が 12.5時間です（目安は 10時間以内）' },
];
const VIOLATIONS_BLOCKER = [
  { severity: 'BLOCKER', code: 'RATIO_UNMET', day: '2026-11-05', slot: '16:30-17:00', staff: '', message: '3歳児の保育士が 2名必要ですが 1名しか配置されていません' },
  { severity: 'BLOCKER', code: 'RATIO_UNMET', day: '2026-11-05', slot: '08:00-08:30', staff: '', message: '1・2歳児の職員が 2名必要ですが 1名しか配置されていません' },
  { severity: 'WARNING', code: 'DAILY_CAP', day: '2026-11-04', slot: '', staff: 'S-03 三島 慧', message: '1日の勤務が 9時間0分です（施設の上限 8時間45分を超えています）' },
  { severity: 'WARNING', code: 'REST_SHORT', day: '2026-11-04', slot: '', staff: 'S-06 平賀 あかり', message: '前勤務との間隔が 10時間30分です（労働基準法の最低11時間に満たしません）' },
  { severity: 'WARNING', code: 'PREF_MISS', day: '2026-11-06', slot: '', staff: 'S-12 水無月 慧太', message: '出勤希望日でしたが勤務が割り当てられませんでした' },
  { severity: 'INFO', code: 'FAIRNESS_SPREAD', day: '2026-11-04', slot: '', staff: '', message: '勤務時間の最大と最小の差が 12.5時間です（目安は 10時間以内）' },
];

/* --- 園児と登園予定時刻（画面1） -----------------------------------------
 * 登園時刻の優先順（提案 2.9.1）:
 *   1 実績打刻 check_in_at（対象日が今日以前）
 *   2 その日の上書き attendance_records.planned_check_in_time
 *   3 園児ごとの既定値 child_planned_arrival_defaults
 *   4 保育必要量区分の normal_start_time
 *   5 開園時刻（shift_facility_settings.day_open）
 * どの段階で補完したかを必ず画面に出す。
 */
/* 區分の開始時刻は施設の開園時刻（07:30）以上にする。開園前の登園は指定できない。 */
const CARE_CATEGORIES = [
  { key: 'standard', name: '標準（11時間）', start: '07:30', end: '18:15' },
  { key: 'short', name: '短時間（8時間）', start: '08:30', end: '16:45' },
  { key: 'long', name: '長期（12時間）', start: '07:30', end: '19:00' },
];

/* 架空の園児62名。実在する園児ではない。 */
const CHILDREN_ALL = (function () {
  const family = ['青柳', '石井', '井上', '遠藤', '大野', '岡田', '小川', '加藤', '木村', '工藤',
    '小林', '斉藤', '坂本', '佐々木', '佐藤', '鈴木', '高橋', '田中', '谷口', '中島',
    '中村', '西村', '橋本', '林', '原田', '藤田', '松本', '村上', '森', '山口',
    '山田', '山本', '吉田', '渡辺', '渡部'];
  const given = ['あかり', 'いずみ', 'うみの', 'えま', 'かける', 'くみ', 'けいすけ', 'こうた', 'さくら', 'しおん',
    'すず', 'たいら', 'ちひろ', 'つばさ', 'てんま', 'なぎさ', 'はな', 'ひなた', 'ふうた', 'ほな',
    'まひろ', 'みお', 'むすび', 'めい', 'やすひ', 'ゆい', 'りお', 'れお', 'わか', 'ゆき'];
  const out = [];
  for (let i = 0; i < 62; i += 1) {
    const cat = i < 14 ? CARE_CATEGORIES[1]
      : (i % 7 === 0 ? CARE_CATEGORIES[2] : CARE_CATEGORIES[0]);
    /* i % 6 === 0 の園児は既定値未設定。保育必要量区分か開園時刻にフォールバックする。 */
    const needDefault = i % 6 !== 0;
    out.push({
      id: 'C-' + pad2(i + 1),
      name: family[i % family.length] + ' ' + given[i % given.length],
      category: cat.key,
      categoryName: cat.name,
      categoryStart: cat.start,
      needDefault: needDefault,
      planned: needDefault ? (i % 3 === 0 ? '08:00' : '07:30') : '',
      /* 対象日が今日より前の日では、実績打刻が優先される。 */
      checkedInOn: i % 11 === 0,
    });
  }
  return out;
})();

const ARRIVAL_OVERRIDE_REASONS = ['通院の予定', '園内の行事', '臨休の前日', '保護者への引き渡し', 'その他'];

const ARRIVAL_OVERRIDES_DEFAULT = [
  { child: 'C-02', date: '2026-11-10', planned: '09:30', reason: '通院の予定' },
  { child: 'C-05', date: '2026-11-17', planned: '10:00', reason: '園内の行事' },
  { child: 'C-09', date: '2026-11-24', planned: '08:30', reason: '臨休の前日' },
];

function childVariant(id) {
  const base = {
    default: CHILDREN_ALL,
    empty: CHILDREN_ALL.map(function (c) {
      return Object.assign({}, c, { needDefault: false, planned: '', checkedInOn: false });
    }),
    partial: CHILDREN_ALL.map(function (c, i) {
      return Object.assign({}, c, {
        needDefault: i < 5,
        planned: i < 5 ? '07:30' : '',
      });
    }),
    /* type="time" は 08:90 のような不正値を受け付けない。検証可能な誤りは
   「閉園より後」と「開園より前」の2種類。時刻の書式そのものは入力欄が防ぐ。 */
invalid: CHILDREN_ALL.map(function (c, i) {
      return Object.assign({}, c, {
        needDefault: true,
        planned: i === 3 ? '19:45' : (i === 7 ? '07:00' : '07:30'),
      });
    }),
  };
  return (base[id] || base.default).map(function (c) { return Object.assign({}, c); });
}

function overridesVariant(id) {
  const base = {
    default: ARRIVAL_OVERRIDES_DEFAULT,
    empty: [],
    partial: ARRIVAL_OVERRIDES_DEFAULT.slice(0, 1),
    invalid: ARRIVAL_OVERRIDES_DEFAULT.concat([
      { child: 'C-01', date: '2026-10-01', planned: '09:00', reason: '対象月外の入力' },
      { child: 'C-02', date: '2026-11-11', planned: '19:50', reason: '閉園時刻より後' },
    ]),
  };
  return (base[id] || base.default).map(function (o) { return Object.assign({}, o); });
}

/* 優先順位を解決し、どの段階で補完したかを返す。 */
function resolveArrival(child, date, ctx) {
  if (child.checkedInOn && date < ctx.today) {
    return { at: '実績打刻', level: 1, time: '08:12', why: '対象日が今日以前なので実績打刻が優先されます' };
  }
  const ov = ctx.overrides.filter(function (o) {
    return o.child === child.id && o.date === date;
  })[0];
  if (ov) { return { at: 'その日の上書き', level: 2, time: ov.planned, why: '例外日として上書きされています' }; }
  if (child.planned) { return { at: '園児ごとの既定値', level: 3, time: child.planned, why: '園児ごとに設定した既定値を使います' }; }
  if (child.categoryStart) {
    return { at: '保育必要量区分', level: 4, time: child.categoryStart, why: '既定値が未設定なので保育必要量区分の開始時刻まで下がります' };
  }
  return { at: '開園時刻', level: 5, time: ctx.dayOpen, why: '区分も未設定なので開園時刻まで遡ります' };
}
