"""Two-account archive; one export and Git deployment per scheduled run."""
import argparse
import contextlib
import html
import json
import os
from pathlib import Path
import sqlite3
import sys
import fcntl
from datetime import datetime
from zoneinfo import ZoneInfo
import subprocess

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
ACCOUNTS = [('1644724561', '波浪理论学习'), ('1576218000', '李笑来')]


def today():
    return datetime.now(ZoneInfo('America/Toronto')).date().isoformat()


def history_state():
    path = BASE / 'accounts' / ACCOUNTS[1][0] / 'backfill.json'
    return json.loads(path.read_text()) if path.exists() else {'page': 1, 'complete': False}


def lock_active(path):
    with open(path, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def second_due(state):
    return state.get('1576218000') != today()


@contextlib.contextmanager
def account_context(uid):
    import scraper
    import export_static
    original = (scraper.DB_PATH, export_static.DB_PATH, export_static.STATIC_DIR, os.getcwd())
    folder = BASE if uid == ACCOUNTS[0][0] else BASE / 'accounts' / uid
    folder.mkdir(parents=True, exist_ok=True)
    output = STATIC if uid == ACCOUNTS[0][0] else STATIC / uid
    output.mkdir(parents=True, exist_ok=True)
    scraper.DB_PATH = export_static.DB_PATH = str(folder / 'weibo_data.db')
    export_static.STATIC_DIR = str(output)
    os.chdir(folder)
    try:
        scraper.init_db()
        yield folder, output
    finally:
        scraper.DB_PATH, export_static.DB_PATH, export_static.STATIC_DIR, cwd = original
        os.chdir(cwd)


def export_account(uid):
    import export_static
    with account_context(uid):
        export_static.export_stats()
        export_static.export_posts()


def build_site():
    source = (STATIC / 'app.js').read_text()
    source = source.split('// ── Cookie management')[0]
    start = source.index('async function fetchWithFallback(')
    end = source.index('async function fetchStats()')
    source = source[:start] + "async function fetchWithFallback(endpoint, staticFile) { const res = await fetch('./' + staticFile); if (!res.ok) throw new Error('Data unavailable'); return await res.json(); }\n\n" + source[end:]
    (STATIC / 'archive.js').write_text(source)
    cards = []
    for uid, fallback in ACCOUNTS:
        folder = BASE if uid == ACCOUNTS[0][0] else BASE / 'accounts' / uid
        name = fallback
        db = folder / 'weibo_data.db'
        if db.exists():
            with sqlite3.connect(db) as conn:
                row = conn.execute('SELECT raw_json FROM posts ORDER BY created_at_ts DESC LIMIT 1').fetchone()
                if row:
                    raw = json.loads(row[0] or '{}')
                    name = raw.get('user', {}).get('screen_name') or raw.get('mblog', {}).get('user', {}).get('screen_name') or name
        target = STATIC / uid
        target.mkdir(parents=True, exist_ok=True)
        if uid == ACCOUNTS[0][0]:
            posts = json.loads((STATIC / 'posts.json').read_text())
            for post in posts:
                post['images'] = ['../' + p if p.startswith('images/') else p for p in post.get('images', [])]
            (target / 'posts.json').write_text(json.dumps(posts, ensure_ascii=False, separators=(',', ':')))
            (target / 'stats.json').write_bytes((STATIC / 'stats.json').read_bytes())
        stats_path = target / 'stats.json'
        stats = json.loads(stats_path.read_text()) if stats_path.exists() else {'posts': 0, 'comments': 0}
        safe = html.escape(name)
        pending = uid == ACCOUNTS[1][0] and not history_state()['complete']
        status = '历史补全中 · 每天更新一次' if pending else ('每天更新一次' if uid == ACCOUNTS[1][0] else '每天更新三次')
        # Static-only account pages deliberately do not include cookie-management controls.
        page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>{safe} · 微博归档</title><link rel="stylesheet" href="../style.css"></head><body><div class="container"><nav style="margin:24px 0"><a href="../" style="color:#60a5fa">← 全部账号</a>　<a href="https://weibo.com/u/{uid}" target="_blank" rel="noopener" style="color:#94a3b8">微博原主页 ↗</a></nav><header><h1>{safe}</h1><div class="stats" id="stats">正在加载…</div></header><main id="timeline"><div class="loading">正在加载博文…</div></main></div><script src="../archive.js"></script></body></html>'''
        page = page.replace('<main id="timeline">', f'<p style="color:#94a3b8">{status}</p><main id="timeline">')
        (target / 'index.html').write_text(page)
        cards.append(f'<a class="card" href="./{uid}/"><span class="eyebrow">WEIBO ARCHIVE · {uid}</span><h2>{safe}<span>↗</span></h2><p>{stats["posts"]:,} 条博文 <b>·</b> {stats["comments"]:,} 条评论</p><p>{status}</p><span class="open">查看归档 →</span></a>')
    homepage = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>微博归档 · Weibo Archive</title><style>*{box-sizing:border-box}body{margin:0;background:#101827;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1000px;margin:auto;padding:90px 28px}.tag{color:#60a5fa;font-size:12px;letter-spacing:.18em}h1{font-size:clamp(34px,6vw,56px);letter-spacing:-.04em;margin:18px 0}main>p{color:#94a3b8;line-height:1.8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:22px;margin-top:48px}.card{color:inherit;text-decoration:none;background:#1e293b;border:1px solid #334155;border-radius:18px;padding:30px;transition:transform .2s,border-color .2s}.card:hover{transform:translateY(-4px);border-color:#60a5fa}.card:focus-visible{outline:3px solid #60a5fa;outline-offset:4px}.eyebrow{font-size:10px;letter-spacing:.1em;color:#94a3b8}h2{font-size:24px;margin:24px 0 18px}h2 span{float:right;color:#60a5fa}.card p{font-size:14px;color:#94a3b8}.card b{padding:0 8px}.open{display:block;color:#60a5fa;font-size:14px;margin-top:40px}footer{color:#64748b;font-size:12px;margin-top:50px}</style></head><body><main><div class="tag">PERSONAL READING COLLECTION</div><h1>微博归档</h1><p>把值得保留的记录，留在这里。<br>选择一个账号，浏览博文、图片与评论。</p><div class="grid">CARDS</div><footer>每天自动同步 · 内容来自各账号公开微博</footer></main></body></html>'''
    (STATIC / 'index.html').write_text(homepage.replace('CARDS', ''.join(cards)))
    for p in STATIC.rglob('posts.json'):
        data = json.loads(p.read_text())
        for item in data:
            item.pop('raw_json', None)
        p.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
        if p.stat().st_size > 25 * 1024 * 1024:
            raise RuntimeError(f'Cloudflare asset exceeds 25 MiB: {p}')


def backfill(uid, cookie):
    import scraper
    with account_context(uid) as (folder, _):
        checkpoint = folder / 'backfill.json'
        state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {'page': 1, 'complete': False}
        if state['complete']:
            return
        session = scraper.requests.Session()
        ua = scraper._pick_ua()
        scraper._warmup_session(session, uid, cookie, ua)
        try:
            while True:
                page = state['page']
                cards = scraper.get_posts(uid, f'107603{uid}', cookie, page, session=session, ua=ua)
                if cards == 'cookie_expired':
                    raise RuntimeError('Cookie expired; please sign in to Weibo again.')
                if not cards:
                    state['complete'] = True
                    checkpoint.write_text(json.dumps(state))
                    print(f'History finished for {uid} at page {page}', flush=True)
                    break
                for card in cards:
                    if card.get('card_type') != 9:
                        continue
                    pid = scraper.save_post(card, cookie, session=session, ua=ua)
                    if pid:
                        for comment in scraper.get_comments(pid, cookie, session=session, ua=ua):
                            scraper.save_comment_with_reply(pid, comment, uid)
                        scraper._jitter(1.5, .8)
                state['page'] += 1
                checkpoint.write_text(json.dumps(state))
                print(f'History {uid}: completed page {page}', flush=True)
                scraper._jitter(3, 1.5)
        finally:
            session.close()


def publish():
    with open(BASE / '.publish.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for uid, _ in ACCOUNTS:
            export_account(uid)
        build_site()
        from git_sync import sync_content
        sync_content()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backfill', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args()
    # A long history import does not block the first account's regular updates.
    lock_name = '.backfill.lock' if args.backfill else '.archive.lock'
    with open(BASE / lock_name, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another archive run is active; skipping.', flush=True)
            return
        import scraper
        from cli_backup import get_cookie
        stamp_path = BASE / 'accounts' / 'update-state.json'
        stamps = json.loads(stamp_path.read_text()) if stamp_path.exists() else {}
        if not args.export_only:
            cookie = get_cookie()
            if not cookie:
                raise RuntimeError('No Weibo login cookie available.')
            if args.backfill:
                backfill(ACCOUNTS[1][0], cookie)
                stamps[ACCOUNTS[1][0]] = today()
            else:
                for uid, _ in ACCOUNTS:
                    if uid == ACCOUNTS[1][0]:
                        if lock_active(BASE / '.backfill.lock'):
                            print('History import active; skipping duplicate second-account scrape.', flush=True)
                            continue
                        if not history_state()['complete']:
                            with open(BASE / 'history-backfill.log', 'a') as log:
                                subprocess.Popen([sys.executable, '-u', str(BASE / 'multi_archive.py'), '--backfill'], cwd=BASE, stdout=log, stderr=log, start_new_session=True)
                            print('Resumed unfinished history import in background.', flush=True)
                            continue
                        if not second_due(stamps):
                            print('Second account already updated today; skipping.', flush=True)
                            continue
                    with account_context(uid):
                        result = scraper.run_scraper(uid, cookie, days_back=int(os.getenv('WEIBO_DAYS', '3')))
                        if result == 'cookie_expired':
                            raise RuntimeError('Weibo login expired.')
                    if uid == ACCOUNTS[1][0]:
                        stamps[uid] = today()
            stamp_path.parent.mkdir(parents=True, exist_ok=True)
            stamp_path.write_text(json.dumps(stamps))
        publish()


if __name__ == '__main__':
    main()
