'use strict';

/* ==================== 主题 ==================== */
(function initTheme() {
  const saved = localStorage.getItem('cf-theme') || 'dark';   // 默认深色，与 base.html 的内联脚本保持一致
  document.documentElement.setAttribute('data-theme', saved);
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('themeBtn');
    const sync = () => btn.textContent =
      document.documentElement.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
    sync();
    btn.onclick = () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('cf-theme', next);
      sync();
    };
  });
})();

/* ==================== 心跳 + 关闭即退出 ==================== */
function beat() { fetch('/heartbeat').catch(() => {}); }
beat();
setInterval(beat, 5000);

// 区分"真正关闭页面"与"应用内跳转"（查询/刷新会触发页面卸载，不能误杀进程）
let _navigating = false;
function markNav() { _navigating = true; }
window.addEventListener('pagehide', () => {
  if (!_navigating) { try { navigator.sendBeacon('/shutdown'); } catch (e) {} }
});

// 顶栏导航、弱点墙深链等站内 <a> 跳转同样会卸载页面，统一标记，免得发出没必要的关闭信标。
// 页内锚点（#user-xxx）不卸载页面，必须排除——否则标记后真关页面时就发不出信标了。
document.addEventListener('click', (e) => {
  const a = e.target && e.target.closest && e.target.closest('a[href]');
  if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
  const href = a.getAttribute('href');
  if (!href || href.startsWith('#')) return;
  try {
    if (new URL(href, location.href).origin === location.origin) markNav();
  } catch (err) { /* 非法 href 忽略 */ }
}, true);

/* ==================== Toast ==================== */
function toast(msg, type = 'info') {
  const box = document.getElementById('toasts');
  if (!box) { alert(msg); return; }
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2600);
}

/* ==================== 加载遮罩 ==================== */
function showOverlay(tip) {
  const o = document.getElementById('overlay');
  if (tip) o.querySelector('.tip').textContent = tip;
  o.classList.add('show');
}

/* ==================== 大部队 ==================== */
// 首页只处理单个用户，这里取输入框里的第一个名字（用户可能习惯性地打了逗号）
function addCurrentToArmy() {
  const handle = document.getElementById('handlesInput').value.split(/[,，]/)[0].trim();
  if (!handle) { toast('请先输入用户名', 'err'); return; }
  fetch('/api/add_army?handle=' + encodeURIComponent(handle), { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      toast(d.msg, d.success ? 'ok' : 'err');
      if (d.success) { markNav(); setTimeout(() => location.reload(), 700); }
    })
    .catch(() => toast('加入失败', 'err'));
}

function removeMember(handle) {
  if (!confirm(`确定将【${handle}】移出大部队？`)) return;
  fetch('/api/remove_army?handle=' + encodeURIComponent(handle), { method: 'POST' })
    .then(r => r.json())
    .then(d => { toast(d.msg, d.success ? 'ok' : 'err'); if (d.success) { markNav(); setTimeout(() => location.reload(), 600); } });
}

function refreshArmy(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 刷新中…'; }
  fetch('/api/refresh_army', { method: 'POST' })
    .then(r => r.json())
    .then(d => { toast(d.msg, 'ok'); markNav(); setTimeout(() => location.reload(), 700); })
    .catch(() => { toast('刷新失败', 'err'); if (btn) { btn.disabled = false; btn.textContent = '🔄 刷新数据'; } });
}

function queryMember(handle) {
  document.getElementById('handlesInput').value = handle;
  showOverlay('正在查询 ' + handle + ' …');
  markNav();
  document.getElementById('searchForm').submit();
}

/* ==================== 题单收藏（推荐题 / 刷题器 / 合练题单通用） ==================== */
function todoAdd(el) {
  const d = el.dataset;
  const params = new URLSearchParams({ key: d.key || '', name: d.name || '', rating: d.rating || 0, tags: d.tags || '' });
  fetch('/api/todo/add?' + params.toString(), { method: 'POST' })
    .then(r => r.json())
    .then(res => {
      toast(res.msg, res.success ? 'ok' : 'info');
      if (res.success) { el.textContent = '★'; el.classList.add('starred'); }
    })
    .catch(() => toast('加入题单失败', 'err'));
}

/* ==================== 表格 ==================== */
function toggleDetails(handle) {
  const el = document.getElementById('details-' + handle);
  el.style.display = el.style.display === 'block' ? 'none' : 'block';
}

function exportCSV() {
  const rows = [];
  document.querySelectorAll('#teamTable tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('th,td')).map(td => {
      const t = (td.querySelector('.contest-row') || td).innerText.replace(/\s+/g, ' ').trim();
      return '"' + t.replace(/"/g, '""') + '"';
    });
    rows.push(cells.join(','));
  });
  const blob = new Blob(['﻿' + rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'cf_team.csv';
  a.click();
  toast('已导出 cf_team.csv', 'ok');
}

/* ==================== 比赛筛选 ==================== */
document.addEventListener('DOMContentLoaded', () => {
  const filter = document.getElementById('contestFilter');
  if (filter) {
    filter.querySelectorAll('.chip').forEach(chip => {
      chip.onclick = () => {
        filter.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        const lv = chip.dataset.lv;
        document.querySelectorAll('.contest-item').forEach(it => {
          it.classList.toggle('dimmed', lv !== 'all' && it.dataset.lv !== lv);
        });
      };
    });
  }

  // 查询提交时显示遮罩 + 标记为应用内跳转（避免被当成关闭页面）
  const form = document.getElementById('searchForm');
  if (form) form.addEventListener('submit', () => { markNav(); showOverlay('正在查询 Codeforces，请稍候…'); });

  // 渲染 Rating 走势详图（响应宽度变化重绘）
  document.querySelectorAll('.rating-chart').forEach(renderRatingChart);
  let _rz;
  window.addEventListener('resize', () => {
    clearTimeout(_rz);
    _rz = setTimeout(() => document.querySelectorAll('.rating-chart').forEach(renderRatingChart), 200);
  });
});

/* ==================== Rating 走势详图 ==================== */
const RC_BANDS = [
  [0, 1200, '#808080'], [1200, 1400, '#008000'], [1400, 1600, '#03a89e'],
  [1600, 1900, '#0000ff'], [1900, 2100, '#aa00aa'], [2100, 2400, '#ff8c00'],
  [2400, 3000, '#ff0000'], [3000, 9999, '#ff0000'],
];
let _rcUid = 0;

function rcRankColor(r) {
  if (r >= 3000) return '#ff0000'; if (r >= 2400) return '#ff2d2d';
  if (r >= 2100) return '#ff8c00'; if (r >= 1900) return '#aa00aa';
  if (r >= 1600) return '#3b6ef0'; if (r >= 1400) return '#03a89e';
  if (r >= 1200) return '#008000'; return '#808080';
}
function rcEsc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function renderRatingChart(host) {
  let data = host._rh;
  if (!data) {
    const node = host.querySelector('.rc-data');
    if (!node) return;
    try { data = JSON.parse(node.textContent); } catch (e) { return; }
    host._rh = data;
  }
  if (!data || data.length < 2) return;

  const W = Math.max(320, host.clientWidth || 600), H = 300;
  const L = 46, R = 16, T = 16, B = 30;
  const iW = W - L - R, iH = H - T - B;
  const ratings = data.map(d => d.new_rating);
  let yMin = Math.floor((Math.min(...ratings) - 60) / 100) * 100;
  let yMax = Math.ceil((Math.max(...ratings) + 60) / 100) * 100;
  yMin = Math.max(0, yMin); if (yMax - yMin < 200) yMax = yMin + 200;
  const X = i => L + (i / (data.length - 1)) * iW;
  const Y = r => T + (1 - (r - yMin) / (yMax - yMin)) * iH;
  const uid = ++_rcUid;

  let svg = `<svg class="rc-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  svg += `<defs><linearGradient id="rcg${uid}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#3498db" stop-opacity="0.28"/>
    <stop offset="1" stop-color="#3498db" stop-opacity="0"/></linearGradient></defs>`;

  // 等级色带
  for (const [lo, hi, col] of RC_BANDS) {
    if (hi <= yMin || lo >= yMax) continue;
    const top = Y(Math.min(hi, yMax)), bot = Y(Math.max(lo, yMin));
    svg += `<rect class="rc-band" x="${L}" y="${top.toFixed(1)}" width="${iW}" height="${(bot - top).toFixed(1)}" fill="${col}"/>`;
  }

  // 横向网格 + Y 轴刻度
  const range = yMax - yMin;
  const step = range <= 600 ? 100 : range <= 1200 ? 200 : range <= 2400 ? 400 : 600;
  for (let r = yMin; r <= yMax; r += step) {
    const y = Y(r);
    svg += `<line class="rc-grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    svg += `<text class="rc-axis" x="${L - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${r}</text>`;
  }

  // X 轴日期刻度（约 5 个）
  const ticks = Math.min(5, data.length);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round(k * (data.length - 1) / (ticks - 1 || 1));
    const dt = new Date(data[i].time * 1000);
    const lab = `${dt.getFullYear()}/${String(dt.getMonth() + 1).padStart(2, '0')}`;
    svg += `<text class="rc-axis" x="${X(i).toFixed(1)}" y="${H - 10}" text-anchor="middle">${lab}</text>`;
  }

  // 面积 + 折线
  const pts = data.map((d, i) => [X(i), Y(d.new_rating)]);
  const line = 'M' + pts.map(p => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L ');
  const base = Y(yMin).toFixed(1);
  svg += `<path class="rc-area" fill="url(#rcg${uid})" d="${line} L ${pts[pts.length - 1][0].toFixed(1)} ${base} L ${pts[0][0].toFixed(1)} ${base} Z"/>`;
  svg += `<path class="rc-line" d="${line}"/>`;

  // 数据点
  data.forEach((d, i) => {
    svg += `<circle class="rc-dot" cx="${pts[i][0].toFixed(1)}" cy="${pts[i][1].toFixed(1)}" r="3.5" fill="${rcRankColor(d.new_rating)}" data-i="${i}"/>`;
  });
  svg += `</svg>`;
  host.innerHTML = svg;

  host.querySelectorAll('.rc-dot').forEach(dot => {
    dot.addEventListener('mouseenter', e => rcShowTip(e.target, data[+e.target.dataset.i]));
    dot.addEventListener('mouseleave', rcHideTip);
  });
}

function _rcTip() {
  let t = document.querySelector('.rc-tooltip');
  if (!t) { t = document.createElement('div'); t.className = 'rc-tooltip'; document.body.appendChild(t); }
  return t;
}
function rcShowTip(dot, d) {
  const t = _rcTip();
  const dt = new Date(d.time * 1000);
  const ds = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  const up = d.rating_change > 0;
  t.innerHTML = `<span class="rc-tt-name">${rcEsc(d.name)}</span>
    排名 #${d.rank}<br>${d.old_rating} → <b>${d.new_rating}</b>
    <span style="color:${up ? '#2ecc71' : '#e74c3c'};font-weight:700;">(${up ? '+' : ''}${d.rating_change})</span><br>
    <span style="opacity:.65;">${ds}</span>`;
  t.style.display = 'block';
  const r = dot.getBoundingClientRect();
  const tw = t.offsetWidth, th = t.offsetHeight;
  let left = Math.max(8, Math.min(r.left + r.width / 2 - tw / 2, window.innerWidth - tw - 8));
  let top = r.top - th - 10; if (top < 8) top = r.bottom + 10;
  t.style.left = left + 'px'; t.style.top = top + 'px';
}
function rcHideTip() { const t = document.querySelector('.rc-tooltip'); if (t) t.style.display = 'none'; }
