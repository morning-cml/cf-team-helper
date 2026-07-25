'use strict';
/* 刷题器：标签多选 + 调 /api/pick 出题，结果客户端渲染。
   依赖 app.js 提供的全局 toast()。 */

function pkSelectedTags() {
  return Array.from(document.querySelectorAll('#pkTags .chip.active')).map(c => c.dataset.tag);
}
function pkClearTags() {
  document.querySelectorAll('#pkTags .chip.active').forEach(c => c.classList.remove('active'));
}
function pkEsc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#pkTags .chip').forEach(chip => {
    chip.onclick = () => chip.classList.toggle('active');
  });
  pkApplyUrlParams();      // 支持从弱点墙等处深链预填并自动出题
});

// 读取 URL 参数（rating_min/max、tags、count、mode、exclude、auto）预填表单
function pkApplyUrlParams() {
  const q = new URLSearchParams(window.location.search);
  if (![...q.keys()].length) return;
  const set = (id, v) => { if (v) document.getElementById(id).value = v; };
  set('pkMin', q.get('rating_min'));
  set('pkMax', q.get('rating_max'));
  set('pkCount', q.get('count'));
  set('pkExclude', q.get('exclude'));
  set('pkMode', q.get('mode'));
  const want = new Set((q.get('tags') || '').split(',').map(t => t.trim().toLowerCase()).filter(Boolean));
  if (want.size) {
    document.querySelectorAll('#pkTags .chip').forEach(chip => {
      if (want.has(chip.dataset.tag.toLowerCase())) chip.classList.add('active');
    });
  }
  if (q.get('auto') === '1') pkGenerate(document.getElementById('pkGo'));
}

function pkGenerate(btn) {
  const params = new URLSearchParams({
    rating_min: document.getElementById('pkMin').value || 0,
    rating_max: document.getElementById('pkMax').value || 3500,
    count:      document.getElementById('pkCount').value || 12,
    mode:       document.getElementById('pkMode').value,
    tags:       pkSelectedTags().join(','),
    exclude:    document.getElementById('pkExclude').value.trim(),
  });
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 出题中…'; }
  fetch('/api/pick?' + params.toString())
    .then(r => r.json())
    .then(d => { d.success ? pkRender(d) : toast(d.msg || '出题失败', 'err'); })
    .catch(() => toast('网络错误，请重试', 'err'))
    .finally(() => { if (btn) { btn.disabled = false; btn.textContent = '🎲 出题'; } });
}

function pkRender(d) {
  const card = document.getElementById('pkResultCard');
  const box = document.getElementById('pkResult');
  const title = document.getElementById('pkResultTitle');
  box.innerHTML = '';
  if (!d.problems.length) {
    title.textContent = '没有符合条件的题（区间太窄、标签太挑，或都做过了）';
    card.style.display = 'block';
    return;
  }
  let t = `抽取 ${d.count} 道`;
  if (d.pool_total) t += ` / 命中题库 ${d.pool_total} 题`;
  if (d.excluded) t += ` · 已排除你做过的 ${d.excluded} 题`;
  title.textContent = t;
  d.problems.forEach(p => {
    const a = document.createElement('a');
    a.className = 'reco-card';
    a.href = p.url;
    a.target = '_blank';
    a.innerHTML = `<span class="star" title="加入题单" onclick="event.preventDefault();event.stopPropagation();todoAdd(this)"`
      + ` data-key="${pkEsc(p.key)}" data-name="${pkEsc(p.name)}" data-rating="${p.rating}" data-tags="${pkEsc(p.tags.join(','))}">☆</span>`
      + `<span class="reco-name">${pkEsc(p.name)}</span> <span class="reco-rating">${p.rating}</span>`
      + `<div style="margin-top:6px;">`
      + p.tags.slice(0, 4).map(t => `<span class="chiptag">${pkEsc(t)}</span>`).join('')
      + `</div>`;
    box.appendChild(a);
  });
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
