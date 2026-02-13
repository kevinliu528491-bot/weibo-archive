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

            const commentsHtml = comments.length > 0
                ? `<div class="comments-section">
                    ${comments.map(renderComment).join('')}
                   </div>`
                : '';

            const date = new Date(post.created_at_ts * 1000).toLocaleString();

            let imagesHtml = '';
            // Handle both stringified images (from DB) and array images (from JSON)
            let imgList = post.images;
            if (typeof imgList === 'string') {
                try { imgList = JSON.parse(imgList); } catch (e) { imgList = []; }
            }

            if (imgList && imgList.length > 0) {
                imagesHtml = `<div class="post-images">
                    ${imgList.map(img => `<a href="${img}" target="_blank"><img src="${img}" loading="lazy"></a>`).join('')}
                </div>`;
            }

            card.innerHTML = `
                <div class="post-header">
                    <span class="post-date">${date}</span>
                </div>
                <div class="post-content">${post.text}</div>
                ${imagesHtml}
                <div class="post-footer">
                    <span>Reposts: ${post.reposts_count}</span>
                    <span>Comments: ${post.comments_count}</span>
                    <span>Likes: ${post.attitudes_count}</span>
                </div>
                <div class="comments-section" id="comments-${post.id}">
                    ${commentsHtml}
                </div>
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
            <div class="comment-user">@${comment.user_name}</div>
            <div class="comment-text">${comment.text}</div>
            ${comment.reply_text ? `
                <div class="reply-box">
                    <div class="reply-label">Blogger Replied:</div>
                    <div class="reply-text">${comment.reply_text}</div>
                </div>
            ` : ''}
        </div>
    `;
}

// Init
fetchStats();
renderPosts();
