"""Publish changed static assets without a second local copy of the archive."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import requests


def deploy_static(static_dir):
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GitHub token unavailable for incremental deployment.')
    api = 'https://api.github.com/repos/kevinliu528491-bot/weibo-archive/git/'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}

    def request(method, path, **kwargs):
        r = requests.request(method, api + path, headers=headers, timeout=90, **kwargs)
        if not r.ok:
            raise RuntimeError(f'GitHub deployment request {path} returned HTTP {r.status_code}')
        return r.json()

    head = request('GET', 'ref/heads/gh-pages')['object']['sha']
    tree = request('GET', 'trees/' + head + '?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError('Production file listing is incomplete; refusing deployment.')
    remote = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
    changes = []
    root = Path(static_dir)
    for file in sorted(root.rglob('*')):
        if not file.is_file() or any(p.startswith('.') for p in file.relative_to(root).parts):
            continue
        content = file.read_bytes()
        sha = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        name = file.relative_to(root).as_posix()
        if remote.get(name) != sha:
            changes.append((name, file))
    if not changes:
        print('Production files already up to date.', flush=True)
        return

    def upload(item):
        name, file = item
        blob = request('POST', 'blobs', json={'encoding': 'base64', 'content': base64.b64encode(file.read_bytes()).decode()})
        return {'path': name, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}

    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(upload, changes))
    # Re-read the head so unrelated updates made during uploads are preserved.
    head = request('GET', 'ref/heads/gh-pages')['object']['sha']
    base_tree = request('GET', 'commits/' + head)['tree']['sha']
    new_tree = request('POST', 'trees', json={'base_tree': base_tree, 'tree': entries})
    commit = request('POST', 'commits', json={'message': 'Update Weibo archives', 'tree': new_tree['sha'], 'parents': [head]})
    request('PATCH', 'refs/heads/gh-pages', json={'sha': commit['sha'], 'force': False})
    print(f'Published {len(changes)} changed assets: {commit["sha"][:12]}', flush=True)
