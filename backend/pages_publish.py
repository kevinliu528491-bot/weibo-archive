"""Publish changed static assets without a second local copy of the archive."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import time
from pathlib import Path
import requests
from dotenv import load_dotenv


def deploy_static(static_dir):
    root = Path(static_dir)
    load_dotenv(root.parent.parent / '.env')
    load_dotenv(root.parent / '.env')
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GitHub token unavailable for incremental deployment.')
    repository = 'https://api.github.com/repos/kevinliu528491-bot/weibo-archive/'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}

    def request(method, path, **kwargs):
        for attempt in range(4):
            delay = 2 ** attempt
            try:
                response = requests.request(
                    method, repository + path, headers=headers, timeout=(10, 90), **kwargs
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise RuntimeError(f'GitHub {method} {path} could not connect after four attempts.') from None
            else:
                if response.ok:
                    return response.json()
                rate_limited = response.status_code == 429 or (
                    response.status_code == 403 and (
                        response.headers.get('Retry-After') or
                        'rate limit' in response.text.lower()
                    )
                )
                if attempt == 3 or not (rate_limited or response.status_code >= 500):
                    raise RuntimeError(f'GitHub {method} {path} returned HTTP {response.status_code}.')
                if rate_limited:
                    retry_after = response.headers.get('Retry-After', '60')
                    delay = int(retry_after) if retry_after.isdigit() else 60
                    reset = response.headers.get('X-RateLimit-Reset', '')
                    if response.headers.get('X-RateLimit-Remaining') == '0' and reset.isdigit():
                        delay = max(delay, int(reset) - int(time.time()))
                    if delay > 180:
                        raise RuntimeError('GitHub rate limit exceeded; the next scheduled run can retry.')
            time.sleep(delay)

    def wait_for_pages(commit):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            checks = request('GET', f'commits/{commit}/check-runs')['check_runs']
            for check in checks:
                if check['app']['slug'] != 'cloudflare-workers-and-pages' or check['name'] != 'Cloudflare Pages':
                    continue
                if check['status'] == 'completed':
                    if check['conclusion'] != 'success':
                        raise RuntimeError(f'Cloudflare Pages deployment {commit[:12]}: {check["conclusion"]}.')
                    print(f'Cloudflare Pages verified deployment {commit[:12]}.', flush=True)
                    return
            time.sleep(15)
        raise RuntimeError(f'Cloudflare Pages deployment {commit[:12]} was still unverified after 15 minutes.')

    head = request('GET', 'git/ref/heads/gh-pages')['object']['sha']
    tree = request('GET', 'git/trees/' + head + '?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError('Production file listing is incomplete; refusing deployment.')
    remote = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
    changes = []
    for file in sorted(root.rglob('*')):
        if file.is_symlink() or not file.is_file() or any(p.startswith('.') for p in file.relative_to(root).parts):
            continue
        content = file.read_bytes()
        sha = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        name = file.relative_to(root).as_posix()
        if remote.get(name) != sha:
            changes.append((name, file))
    if not changes:
        print('Production files already up to date.', flush=True)
        wait_for_pages(head)
        return

    def upload(item):
        name, file = item
        blob = request('POST', 'git/blobs', json={'encoding': 'base64', 'content': base64.b64encode(file.read_bytes()).decode()})
        return {'path': name, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}

    with ThreadPoolExecutor(max_workers=2) as pool:
        entries = list(pool.map(upload, changes))
    base_tree = request('GET', 'git/commits/' + head)['tree']['sha']
    new_tree = request('POST', 'git/trees', json={'base_tree': base_tree, 'tree': entries})
    commit = request('POST', 'git/commits', json={'message': 'Update Weibo archives', 'tree': new_tree['sha'], 'parents': [head]})
    request('PATCH', 'git/refs/heads/gh-pages', json={'sha': commit['sha'], 'force': False})
    print(f'Published {len(changes)} changed assets: {commit["sha"][:12]}', flush=True)
    wait_for_pages(commit['sha'])
