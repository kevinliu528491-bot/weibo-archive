"""Extract the original of a repost without publishing the bulky raw API payload."""
def extract_original(raw, cache=None, resolve_long=None, depth=0):
    original = raw.get('retweeted_status') if isinstance(raw, dict) else None
    if not isinstance(original, dict) or depth >= 5:
        return None
    cache = cache if cache is not None else {}
    pid = str(original.get('id') or original.get('idstr') or '')
    user = original.get('user') or {}
    full = (original.get('longText') or {}).get('longTextContent') or cache.get(pid)
    if original.get('isLongText') and not full and resolve_long and pid and user:
        full = resolve_long(pid)
        if full:
            cache[pid] = full
    images = []
    for pic in original.get('pics') or []:
        url = (pic.get('large') or {}).get('url') or pic.get('url')
        if url and url.startswith(('https://', 'http://')):
            images.append(url)
    if not images and original.get('original_pic'):
        images.append(original['original_pic'])
    uid = str(user.get('id') or '')
    bid = original.get('bid')
    result = {
        'id': pid,
        'author_name': user.get('screen_name') or '原作者',
        'author_id': uid,
        'text': full or original.get('text') or '原微博已不可用。',
        'created_at': original.get('created_at') or '',
        'images': images,
        'url': f'https://weibo.com/{uid}/{bid}' if uid and bid else f'https://m.weibo.cn/detail/{pid}',
        'unavailable': not bool(user),
        'truncated': bool(original.get('isLongText') and not full),
    }
    nested = extract_original(original, cache, resolve_long, depth + 1)
    if nested:
        result['original_post'] = nested
    return result


def walk_originals(post):
    original = post.get('original_post')
    while original:
        yield original
        original = original.get('original_post')


def rebase_images(post, prefix):
    for item in [post, *walk_originals(post)]:
        item['images'] = [prefix + p if p.startswith('images/') else p for p in item.get('images', [])]
