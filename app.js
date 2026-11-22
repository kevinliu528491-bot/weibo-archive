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
    const when = original.created_at ? (Number.isNaN(date.getTime()) ? original.created_at : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })) : '';
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

async function createPostCard(post) {
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

            const date = new Date(post.created_at_ts * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });

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

            return card;
}

function archiveText(post) {
    const template = document.createElement('template');
    let text = post.text || '';
    for (let original = post.original_post; original; original = original.original_post) {
        text += ' ' + original.author_name + ' ' + original.text;
    }
    for (const comment of post.comments || []) {
        text += ' ' + comment.user_name + ' ' + comment.text + ' ' + (comment.reply_text || '');
    }
    template.innerHTML = text;
    return (template.content.textContent || '').normalize('NFKC').toLocaleLowerCase();
}

function setupArchiveFilters(posts, timeline) {
    const panel = document.createElement('section');
    panel.className = 'archive-filters';
    panel.setAttribute('aria-label', '查询博文');
    panel.innerHTML = `
        <div class="filter-controls">
            <label class="search-label">搜索<input type="search" id="archive-search" placeholder="搜索博文、转发原文及评论" autocomplete="off"></label>
            <label>年份<select id="archive-year" aria-label="年份"><option value="">全部年份</option></select></label>
            <label>月份<select id="archive-month" aria-label="月份"><option value="">全部月份</option></select></label>
            <button type="button" id="archive-reset">重置</button>
        </div>
        <p id="archive-results" role="status" aria-live="polite"></p>`;
    timeline.before(panel);
    const search = panel.querySelector('#archive-search');
    const year = panel.querySelector('#archive-year');
    const month = panel.querySelector('#archive-month');
    const status = panel.querySelector('#archive-results');
    const formatter = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'});
    const index = posts.map(post => {
        const parts = formatter.formatToParts(new Date(post.created_at_ts * 1000));
        return {post, text:archiveText(post), year:parts.find(p=>p.type==='year').value, month:parts.find(p=>p.type==='month').value};
    });
    for (const value of [...new Set(index.map(row=>row.year))].sort().reverse()) {
        year.add(new Option(value + '年', value));
    }
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'archive-more';
    more.textContent = '加载更多';
    timeline.after(more);
    let matches = [];
    let shown = 0;
    let revision = 0;
    let timer;

    function updateMonths() {
        const selected = month.value;
        month.replaceChildren(new Option('全部月份', ''));
        const months = [...new Set(index.filter(row=>!year.value || row.year===year.value).map(row=>row.month))].sort();
        for (const value of months) month.add(new Option(Number(value) + '月', value));
        if (months.includes(selected)) month.value = selected;
    }

    async function appendBatch(currentRevision) {
        more.disabled = true;
        const end = Math.min(shown + 40, matches.length);
        const fragment = document.createDocumentFragment();
        for (let i=shown; i<end; i++) {
            const card = await createPostCard(matches[i].post);
            if (currentRevision !== revision) return;
            fragment.append(card);
        }
        timeline.append(fragment);
        shown = end;
        status.textContent = `找到 ${matches.length.toLocaleString()} 条博文，已显示 ${shown.toLocaleString()} 条 · 日期按北京时间`;
        more.hidden = shown >= matches.length;
        more.disabled = false;
    }

    async function filter() {
        const currentRevision = ++revision;
        const words = search.value.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
        matches = index.filter(row=>(!year.value || row.year===year.value) && (!month.value || row.month===month.value) && words.every(word=>row.text.includes(word)));
        shown = 0;
        timeline.replaceChildren();
        more.hidden = true;
        if (!matches.length) {
            status.textContent = '找到 0 条博文 · 日期按北京时间';
            const empty = document.createElement('p');
            empty.className = 'loading';
            empty.textContent = '没有符合条件的博文，请调整关键词或年月。';
            timeline.append(empty);
            return;
        }
        await appendBatch(currentRevision);
    }
    search.addEventListener('input', ()=>{ clearTimeout(timer); timer=setTimeout(()=>filter(),180); });
    year.addEventListener('change', ()=>{clearTimeout(timer);updateMonths();filter();});
    month.addEventListener('change', ()=>{clearTimeout(timer);filter();});
    panel.querySelector('#archive-reset').addEventListener('click', ()=>{
        clearTimeout(timer); search.value=''; year.value=''; updateMonths(); month.value=''; filter();
    });
    more.addEventListener('click', ()=>appendBatch(revision));
    updateMonths();
    return filter();
}

async function renderPosts() {
    const timeline = document.getElementById('timeline');
    try {
        const posts = await fetchWithFallback('posts', 'posts.json');
        await setupArchiveFilters(posts, timeline);
    } catch (error) {
        console.error('Failed to load archive', error);
        timeline.innerHTML = '<div class="loading">博文加载失败，请刷新页面重试。</div>';
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
