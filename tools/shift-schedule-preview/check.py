"""Serve the preview, run the headless self-test, and print a summary.

One process, so there is no long-lived server to keep alive and no Node.js
dependency. Exits non-zero if any self-test step fails.

    venv/Scripts/python.exe tools/shift-schedule-preview/check.py
    venv/Scripts/python.exe tools/shift-schedule-preview/check.py --port 8911
"""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def find_chrome() -> str:
    candidates = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    found = shutil.which('chrome') or shutil.which('msedge')
    if found:
        return found
    raise SystemExit('Chrome or Edge not found; pass --browser with an explicit path.')


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102 - silence request logging
        pass


def serve(directory: Path, port: int) -> ThreadingHTTPServer:
    handler = lambda *a, **kw: QuietHandler(*a, directory=str(directory), **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(('127.0.0.1', port), handler)
    Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8907)
    ap.add_argument('--browser', default=None)
    ap.add_argument('--budget', type=int, default=25000, help='ms of virtual time')
    args = ap.parse_args()

    selftest = HERE / 'selftest.html'
    if not selftest.exists():
        raise SystemExit('selftest.html is missing; run build.py first.')

    httpd = serve(HERE, args.port)
    browser = args.browser or find_chrome()
    profile = tempfile.mkdtemp(prefix='shift-preview-check-')
    try:
        proc = subprocess.run(
            [browser, '--headless=new', '--disable-gpu', '--no-sandbox',
             f'--user-data-dir={profile}', f'--virtual-time-budget={args.budget}',
             '--dump-dom', f'http://127.0.0.1:{args.port}/selftest.html'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        httpd.shutdown()
        raise SystemExit('browser timed out')
    finally:
        httpd.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    match = re.search(r'<pre id="selftest-out">(.*?)</pre>', proc.stdout, re.S)
    if not match:
        print('The self-test did not finish. Browser output follows.', file=sys.stderr)
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        return 2

    report = json.loads(match.group(1))
    for row in report['results']:
        if not row['ok']:
            print(f"FAIL {row['name']} :: {row['detail']}")
    print(f"\n{report['total'] - report['failed']}/{report['total']} steps passed "
          f"({report['failed']} failed) at http://127.0.0.1:{args.port}/")
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
