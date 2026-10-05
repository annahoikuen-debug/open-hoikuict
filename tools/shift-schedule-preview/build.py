"""Build a static shift-schedule preview from the deployed sidebar template; no app/DB imports.

Renders the real ``templates/base.html`` <aside> so the mock reproduces the deployed
navigation, then injects the proposed ``/shifts`` entry. Nothing here imports the
FastAPI app, SQLModel, or SQLite.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMIT = 'ab947ba718a8d2c64da66e2cafb255f01cda14ad'
FILES = ['templates/base.html']

# --- verify the sidebar source is exactly the committed deployment state -------
hashes = {}
for name in FILES:
    raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{COMMIT}:{name}'])
    raw = raw.replace(b'\r\n', b'\n')
    assert raw == (ROOT / name).read_bytes().replace(b'\r\n', b'\n'), name
    hashes[name] = hashlib.sha256(raw).hexdigest()

dirty = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain',
                                '--', 'templates/base.html']).decode('utf-8').strip()
assert not dirty, f'templates/base.html has uncommitted edits: {dirty}'

# --- render only the sidebar, without starting the app -------------------------
env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape())
env.filters['jst_datetime'] = lambda value, fmt='': str(value)
env.globals['static_asset_url'] = lambda name: '/static/' + name

SHIFT_PATH = '/shifts/facility'
rendered = env.get_template('base.html').render(
    request=SimpleNamespace(url=SimpleNamespace(path=SHIFT_PATH), state=SimpleNamespace()),
    current_user=SimpleNamespace(
        staff_id=1, name='確認用園長', role_label='管理者',
        can_manage_child_records=True, can_manage_billing_accounts=True,
        can_manage_shifts=True),
).replace('\n', '\n')

sidebar = re.search(r'<aside\b.*?</aside>', rendered, re.S).group()

# Strip forms and login chrome; this mock is a read-only confirmation surface.
sidebar = re.sub(r'<form\b.*?</form>', '', sidebar, flags=re.S)
sidebar = re.sub(r'<button\b.*?</button>', '', sidebar, flags=re.S)
sidebar = re.sub(r'<script\b.*?</script>', '', sidebar, flags=re.S)

# Existing entries point at '#': this mock only owns /shifts.
sidebar = re.sub(r'href="[^"]*"', 'href="#"', sidebar)
sidebar = sidebar.replace('ログイン中', 'モック用の表示')

# --- insert the proposed entry into 基本業務, after 出欠確認 --------------------
PROPOSED = (
    '\n              '
    '<a href="#view-facility" data-nav="facility" '
    'class="block rounded-xl px-3 py-2.5 text-sm font-medium bg-indigo-50 text-indigo-700">'
    '職員シフト'
    '</a>'
    '<!-- 本提案（docs/shift-schedule-integration-proposal-2026-10-03.md）が追加する項目。'
    '基本業務グループ・出欠確認の直後へ挿入。配備版には存在しない。 -->'
)
anchor = (
    '<a href="#" class="block rounded-xl px-3 py-2.5 text-sm font-medium '
    'text-slate-700 hover:bg-slate-100">出欠確認</a>'
)
assert sidebar.count(anchor) == 1, 'could not locate the 出欠確認 anchor in the sidebar'
sidebar = sidebar.replace(anchor, anchor + PROPOSED)
assert '職員シフト' in sidebar

page = (HERE / 'page.html').read_text(encoding='utf-8')
page = page.replace('<!-- DEPLOYED_SIDEBAR -->', sidebar)
assert 'DEPLOYED_SIDEBAR' not in page
page = '\n'.join(line.rstrip() for line in page.splitlines()) + '\n'

(HERE / 'index.html').write_text(page, encoding='utf-8', newline='\n')

# selftest.html is index.html plus the verification driver, so the whole
# view x state matrix can be exercised in headless Chrome without a driver API.
selftest = page.replace(
    '<script src="app.js"></script>',
    '<script src="app.js"></script>\n<script src="selftest.js"></script>')
assert selftest != page
(HERE / 'selftest.html').write_text(selftest, encoding='utf-8', newline='\n')

(HERE / 'baseline.json').write_text(
    json.dumps({'commit': COMMIT, 'sidebar_source': FILES, 'normalized_sha256': hashes},
               ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

print(f'Built static shift-schedule preview from {COMMIT[:7]}; '
      f'verified {len(FILES)} template file(s). No app, model, or database imported.')
