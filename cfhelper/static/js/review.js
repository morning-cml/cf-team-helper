'use strict';
/* 复盘页：刷题难度散点图（时间 × 题目难度）+ 月度中位难度趋势线 + 同期 Rating 曲线。
   复用 app.js 的全局：RC_BANDS / _rcTip / rcHideTip / rcEsc / toast / markNav / showOverlay。 */

const SC_TREND = '#e67e22', SC_RATING = '#3b6ef0';

function renderScatter(host) {
  // 与 vs.js 同一个坑：下面会用 SVG 覆盖 innerHTML，把数据节点冲掉，
  // resize 重绘时就没数据可读了。先缓存到元素上。
  if (!host._sc) {
    const node = host.querySelector('.sc-data');
    if (!node) return;
    try { host._sc = JSON.parse(node.textContent); } catch (e) { return; }
  }
  const d = host._sc;
  const pts = d.points || [];
  if (pts.length < 2) return;

  const W = Math.max(360, host.clientWidth || 760), H = 340;
  const L = 48, R = 16, T = 14, B = 30;
  const iW = W - L - R, iH = H - T - B;

  const times = pts.map(p => p.t);
  let xMin = Math.min(...times), xMax = Math.max(...times);
  if (xMax === xMin) xMax = xMin + 86400;
  const rs = pts.map(p => p.r).concat((d.rating_line || []).map(p => p.r));
  let yMin = Math.max(0, Math.floor((Math.min(...rs) - 150) / 100) * 100);
  let yMax = Math.ceil((Math.max(...rs) + 150) / 100) * 100;
  if (yMax - yMin < 400) yMax = yMin + 400;

  const X = t => L + ((t - xMin) / (xMax - xMin)) * iW;
  const Y = r => T + (1 - (r - yMin) / (yMax - yMin)) * iH;

  let svg = `<svg class="rc-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for (const [lo, hi, col] of RC_BANDS) {           // 难度色带，和 CF 等级配色一致
    if (hi <= yMin || lo >= yMax) continue;
    const top = Y(Math.min(hi, yMax)), bot = Y(Math.max(lo, yMin));
    svg += `<rect class="rc-band" x="${L}" y="${top.toFixed(1)}" width="${iW}" height="${(bot - top).toFixed(1)}" fill="${col}"/>`;
  }
  const range = yMax - yMin;
  const step = range <= 800 ? 200 : range <= 1600 ? 400 : 600;
  for (let r = yMin; r <= yMax; r += step) {
    const y = Y(r);
    svg += `<line class="rc-grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    svg += `<text class="rc-axis" x="${L - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${r}</text>`;
  }
  for (let k = 0; k < 5; k++) {
    const t = xMin + (xMax - xMin) * k / 4;
    const dt = new Date(t * 1000);
    svg += `<text class="rc-axis" x="${X(t).toFixed(1)}" y="${H - 10}" text-anchor="middle">`
      + `${dt.getFullYear()}/${String(dt.getMonth() + 1).padStart(2, '0')}</text>`;
  }

  // 同期 Rating（细线，作背景参照）
  const line = d.rating_line || [];
  if (line.length >= 2) {
    const p = line.map(x => `${X(x.t).toFixed(1)} ${Y(x.r).toFixed(1)}`).join(' L ');
    svg += `<path d="M${p}" fill="none" stroke="${SC_RATING}" stroke-width="1.6" opacity=".75"/>`;
  }
  // 散点
  pts.forEach((p, i) => {
    svg += `<circle class="sc-dot" cx="${X(p.t).toFixed(1)}" cy="${Y(p.r).toFixed(1)}" r="3"`
      + ` fill="${rcRankColor(p.r)}" data-i="${i}"/>`;
  });
  // 月度中位难度（粗线，趋势看这条）
  const tr = d.trend || [];
  if (tr.length >= 2) {
    const p = tr.map(x => `${X(x.t).toFixed(1)} ${Y(x.r).toFixed(1)}`).join(' L ');
    svg += `<path d="M${p}" fill="none" stroke="${SC_TREND}" stroke-width="3"`
      + ` stroke-linejoin="round" stroke-linecap="round"/>`;
    tr.forEach(x => {
      svg += `<circle cx="${X(x.t).toFixed(1)}" cy="${Y(x.r).toFixed(1)}" r="4"`
        + ` fill="${SC_TREND}" stroke="var(--bg-elev)" stroke-width="1.5"/>`;
    });
  }
  svg += '</svg>';
  host.innerHTML = svg;

  host.querySelectorAll('.sc-dot').forEach(dot => {
    dot.addEventListener('mouseenter', e => {
      const p = pts[+e.target.dataset.i];
      const dt = new Date(p.t * 1000);
      const t = _rcTip();
      t.innerHTML = `<span class="rc-tt-name">${rcEsc(p.n || '（题名未知）')}</span>`
        + `难度 <b style="color:${rcRankColor(p.r)};">${p.r}</b><br>`
        + `<span style="opacity:.65;">${dt.getFullYear()}-`
        + `${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')} 解出</span>`;
      t.style.display = 'block';
      const r = e.target.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left + r.width / 2 - t.offsetWidth / 2,
        window.innerWidth - t.offsetWidth - 8));
      let top = r.top - t.offsetHeight - 10;
      if (top < 8) top = r.bottom + 10;
      t.style.left = left + 'px'; t.style.top = top + 'px';
    });
    dot.addEventListener('mouseleave', rcHideTip);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('rvInput');
  document.querySelectorAll('.pick-army').forEach(chip => {
    chip.onclick = () => { input.value = chip.dataset.h; };
  });
  const form = document.getElementById('rvForm');
  if (form) form.addEventListener('submit', () => { markNav(); showOverlay('正在复盘，请稍候…'); });

  document.querySelectorAll('.sc-chart').forEach(renderScatter);
  let rz;
  window.addEventListener('resize', () => {
    clearTimeout(rz);
    rz = setTimeout(() => document.querySelectorAll('.sc-chart').forEach(renderScatter), 200);
  });
});
