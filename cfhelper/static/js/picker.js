'use strict';
/* 刷题器：标签多选 + 调 /api/pick 出题，结果客户端渲染。
   依赖 app.js 提供的全局 toast()。 */

/* 标签三态：未选 -> 包含(active) -> 排除(banned) -> 未选。
   比"包含框 + 排除框"两个输入省地方，也不用来回切焦点。 */
function pkTagsOf(cls) {
  return Array.from(document.querySelectorAll('#pkTags .chip.' + cls)).map(c => c.dataset.tag);
}
function pkSelectedTags() { return pkTagsOf('active'); }
function pkBannedTags()   { return pkTagsOf('banned'); }
function pkTagMode() {
  const el = document.querySelector('input[name="pkTagMode"]:checked');
  return el ? el.value : 'any';
}
function pkClearTags() {
  document.querySelectorAll('#pkTags .chip').forEach(c => c.classList.remove('active', 'banned'));
  pkTagHint();
}
function pkCycle(chip) {
  if (chip.classList.contains('active')) {
    chip.classList.remove('active'); chip.classList.add('banned');
  } else if (chip.classList.contains('banned')) {
    chip.classList.remove('banned');
  } else {
    chip.classList.add('active');
  }
  pkTagHint();
}
function pkTagHint() {
  const el = document.getElementById('pkTagHint');
  if (!el) return;
  const inc = pkSelectedTags(), ban = pkBannedTags();
  const parts = [];
  if (inc.length) {
    parts.push((pkTagMode() === 'all' ? '必须同时带上：' : '命中任一即可：') + inc.join('、'));
  }
  if (ban.length) parts.push('排除：' + ban.join('、'));
  el.textContent = parts.length ? parts.join('　｜　') : '';
}
function pkEsc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#pkTags .chip').forEach(chip => {
    chip.onclick = () => pkCycle(chip);
  });
  document.querySelectorAll('input[name="pkTagMode"]').forEach(r => {
    r.onchange = pkTagHint;
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
  const asSet = k => new Set((q.get(k) || '').split(',')
    .map(t => t.trim().toLowerCase()).filter(Boolean));
  const want = asSet('tags'), ban = asSet('ban');
  if (want.size || ban.size) {
    document.querySelectorAll('#pkTags .chip').forEach(chip => {
      const t = chip.dataset.tag.toLowerCase();
      if (want.has(t)) chip.classList.add('active');
      else if (ban.has(t)) chip.classList.add('banned');
    });
  }
  if (q.get('tag_mode') === 'all') {
    const el = document.querySelector('input[name="pkTagMode"][value="all"]');
    if (el) el.checked = true;
  }
  pkTagHint();
  if (q.get('auto') === '1') pkGenerate(document.getElementById('pkGo'));
}

function pkGenerate(btn) {
  const params = new URLSearchParams({
    rating_min: document.getElementById('pkMin').value || 0,
    rating_max: document.getElementById('pkMax').value || 3500,
    count:      document.getElementById('pkCount').value || 12,
    mode:       document.getElementById('pkMode').value,
    tags:       pkSelectedTags().join(','),
    ban:        pkBannedTags().join(','),
    tag_mode:   pkTagMode(),
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
      + ` <span class="lg-link" title="洛谷中文题面（约九成 CF 题已收录，少数 ICPC 镜像赛没有）"`
      + ` data-lg="${pkEsc(p.luogu)}" onclick="event.preventDefault();event.stopPropagation();openLuogu(this)">洛谷</span>`
      + `<div style="margin-top:6px;">`
      + p.tags.slice(0, 4).map(t => `<span class="chiptag">${pkEsc(t)}</span>`).join('')
      + `</div>`;
    box.appendChild(a);
  });
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
