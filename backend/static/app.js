function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function safeUrl(value, base = location.href) {
    try {
        const url = new URL(value, base);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (_) { return ''; }
}

function safeRichText(value) {
    const template = document.createElement('template');
    template.innerHTML = String(value ?? '');
    const allowed = new Set(['A','IMG','BR','P','SPAN','STRONG','B','EM','I','DIV','UL','OL','LI','SUP','SUB']);
    for (const element of template.content.querySelectorAll('*')) {
        if (['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','FORM','INPUT'].includes(element.tagName)) {
            element.remove();
            continue;
        }
        if (!allowed.has(element.tagName)) {
            element.replaceWith(...element.childNodes);
            continue;
        }
        const href = element.getAttribute('href');
        const src = element.getAttribute('src');
        const alt = element.getAttribute('alt');
        for (const attribute of [...element.attributes]) element.removeAttribute(attribute.name);
        if (element.tagName === 'A' && href) {
            const url = safeUrl(href, 'https://weibo.com/');
            if (url) { element.href = url; element.target = '_blank'; element.rel = 'noopener noreferrer'; }
        }
        if (element.tagName === 'IMG') {
            const url = src && safeUrl(src, 'https://weibo.com/');
            if (!url) { element.remove(); continue; }
            element.src = url; element.alt = alt || ''; element.loading = 'lazy';
        }
    }
    return template.innerHTML;
}

function renderArchiveImages(images) {
    if (typeof images === 'string') {
        try { images = JSON.parse(images); } catch (_) { images = []; }
    }
    const urls = (images || []).map(url => safeUrl(url)).filter(Boolean);
    if (!urls.length) return '';
    return `<div class="post-images">${urls.map(url => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"><img src="${escapeHtml(url)}" alt="微博图片" loading="lazy"></a>`).join('')}</div>`;
}

function renderOriginal(original) {
    if (!original) return '';
    const author = escapeHtml(original.author_name || '原作者');
    const authorUrl = original.author_id ? `https://weibo.com/u/${encodeURIComponent(original.author_id)}` : '';
    const originalUrl = safeUrl(original.url);
    const date = new Date(original.created_at);
    const when = original.created_at ? (Number.isNaN(date.getTime()) ? original.created_at : date.toLocaleString()) : '';
    return `<section class="original-post" data-original-id="${escapeHtml(original.id)}" aria-label="转发的原微博">
        <div class="original-heading"><span class="original-label">原微博</span>${authorUrl ? `<a href="${authorUrl}" target="_blank" rel="noopener noreferrer">@${author}</a>` : `<span>@${author}</span>`}</div>
        ${when ? `<div class="original-date">${escapeHtml(when)}</div>` : ''}
        ${original.unavailable ? '<p class="original-notice">原微博已不可用，以下为已保存的信息。</p>' : ''}
        <div class="original-content">${safeRichText(original.text)}</div>
        ${renderArchiveImages(original.images)}
        ${renderOriginal(original.original_post)}
        ${original.truncated ? '<p class="original-notice">长文尚未完整获取，可查看原微博。</p>' : ''}
        ${originalUrl ? `<a class="original-link" href="${escapeHtml(originalUrl)}" target="_blank" rel="noopener noreferrer">查看原微博 ↗</a>` : ''}
    </section>`;
}

const API_BASE = '/api/';
const STATIC_BASE = '.'; // Relative path for current directory

/* 
 * Helper to determine if we should fallback to static files.
 * If fetch fails or returns 404 on API, it tries static JSON.
 */
async function fetchWithFallback(endpoint, staticFile) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (!res.ok) throw new Error('API not available');
        return await res.json();
    } catch (e) {
        console.warn(`API failed for ${endpoint}, trying static file ${staticFile}...`);
        try {
            const res = await fetch(`${STATIC_BASE}/${staticFile}`);
            if (!res.ok) throw new Error('Static file not found');
            return await res.json();
        } catch (staticErr) {
            console.error(`Failed to fetch both API and static file for ${endpoint}`, staticErr);
            throw staticErr;
        }
    }
}

async function fetchStats() {
    try {
        const data = await fetchWithFallback('stats', 'stats.json');
        document.getElementById('stats').textContent = `${data.posts} Posts tracked • ${data.comments} Replies found`;

        if (data.last_updated) {
            document.getElementById('stats').textContent += ` • Updated: ${data.last_updated}`;
        }
    } catch (e) {
        console.error('Failed to fetch stats', e);
        document.getElementById('stats').textContent = 'Stats unavailable';
    }
}

async function renderPosts() {
    const timeline = document.getElementById('timeline');
    try {
        // Fetch all posts (with nested comments if coming from static JSON)
        const posts = await fetchWithFallback('posts', 'posts.json');

        if (posts.length === 0) {
            timeline.innerHTML = '<div class="loading">No posts found. Run the scraper first.</div>';
            return;
        }

        timeline.innerHTML = '';

        for (const post of posts) {
            const card = document.createElement('div');
            card.className = 'post-card';
            card.dataset.postId = String(post.id);

            // If comments are already included (static JSON), use them. 
            // Otherwise fetch from API.
            let comments = post.comments || [];
            if (!post.comments) {
                try {
                    const comRes = await fetch(`${API_BASE}posts/${post.id}/comments`);
                    if (comRes.ok) {
                        comments = await comRes.json();
                    }
                } catch (e) {
                    console.warn(`Could not fetch comments for ${post.id}`);
                }
            }

            const commentsHtml = comments.map(renderComment).join('');

            const date = new Date(post.created_at_ts * 1000).toLocaleString();

            const imagesHtml = renderArchiveImages(post.images);

            card.innerHTML = `
                <div class="post-header">
                    <span class="post-date">${date}</span>
                </div>
                <div class="post-content">${safeRichText(post.text)}</div>
                ${imagesHtml}
                ${renderOriginal(post.original_post)}
                <div class="post-footer">
                    <span>Reposts: ${post.reposts_count}</span>
                    <span>Comments: ${post.comments_count}</span>
                    <span>Likes: ${post.attitudes_count}</span>
                </div>
                ${comments.length ? `<div class="comments-section" id="comments-${post.id}">${commentsHtml}</div>` : ''}
            `;

            timeline.appendChild(card);
        }
    } catch (e) {
        console.error('Failed to fetch posts', e);
        timeline.innerHTML = '<div class="loading">Error loading posts. Ensure backend is running or posts.json exists.</div>';
    }
}

function renderComment(comment) {
    return `
        <div class="comment">
            <div class="comment-user">@${escapeHtml(comment.user_name)}</div>
            <div class="comment-text">${safeRichText(comment.text)}</div>
            ${comment.reply_text ? `
                <div class="reply-box">
                    <div class="reply-label">Blogger Replied:</div>
                    <div class="reply-text">${safeRichText(comment.reply_text)}</div>
                </div>
            ` : ''}
        </div>
    `;
}

// Init
fetchStats();
renderPosts();

// ── Cookie management ────────────────────────────
async function checkCookieStatus() {
    const dot = document.getElementById('cookie-dot');
    const msg = document.getElementById('cookie-msg');
    try {
        const res = await fetch('/api/cookie-status');
        if (!res.ok) return;
        const data = await res.json();

        dot.className = 'cookie-dot ' + (data.status === 'ok' ? 'ok' : data.status === 'expired' ? 'expired' : '');

        if (data.status === 'ok') {
            msg.textContent = 'Cookie active';
        } else if (data.status === 'expired') {
            msg.textContent = '⚠ Cookie expired — click Settings to update';
        } else if (!data.has_cookie) {
            msg.textContent = 'No cookie set';
        } else {
            msg.textContent = 'Cookie loaded, waiting for check…';
        }

        if (data.last_checked) {
            const t = new Date(data.last_checked).toLocaleString();
            msg.textContent += ` · Last checked: ${t}`;
        }
    } catch (e) {
        // API not available (static mode)
        document.getElementById('cookie-banner').style.display = 'none';
    }
}

checkCookieStatus();
setInterval(checkCookieStatus, 60_000); // Poll every minute

// Dialog
const overlay = document.getElementById('dialog-overlay');
const openBtn = document.getElementById('open-settings');
const cancelBtn = document.getElementById('dialog-cancel');
const saveBtn = document.getElementById('dialog-save');
const cookieInput = document.getElementById('cookie-input');
const feedback = document.getElementById('dialog-feedback');

openBtn.addEventListener('click', () => {
    overlay.style.display = 'flex';
    cookieInput.value = '';
    feedback.textContent = '';
    feedback.className = 'dialog-feedback';
    cookieInput.focus();
});

cancelBtn.addEventListener('click', () => { overlay.style.display = 'none'; });
overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });

saveBtn.addEventListener('click', async () => {
    const val = cookieInput.value.trim();
    if (!val) {
        feedback.textContent = 'Please paste a cookie value';
        feedback.className = 'dialog-feedback error';
        return;
    }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';

    try {
        const res = await fetch('/api/cookie', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cookie: val }),
        });
        const data = await res.json();
        if (res.ok) {
            feedback.textContent = '✓ Cookie updated successfully';
            feedback.className = 'dialog-feedback success';
            setTimeout(() => { overlay.style.display = 'none'; checkCookieStatus(); }, 1200);
        } else {
            feedback.textContent = data.detail || 'Update failed';
            feedback.className = 'dialog-feedback error';
        }
    } catch (e) {
        feedback.textContent = 'Network error';
        feedback.className = 'dialog-feedback error';
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
    }
});
