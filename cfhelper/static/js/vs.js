'use strict';
/* 对比页：双线 Rating 走势 + 大部队依次填 A/B + 提交遮罩。
   复用 app.js 的全局：RC_BANDS / _rcTip / rcHideTip / rcEsc / toast / markNav / showOverlay。 */

const VS_A = '#3b6ef0', VS_B = '#e67e22';

function vsParse(node) { try { return JSON.parse(node.textContent); } catch (e) { return []; } }

function renderVsChart(host) {
  const A = vsParse(host.querySelector('.vs-a'));
  const B = vsParse(host.querySelector('.vs-b'));
  const hA = host.dataset.a || 'A', hB = host.dataset.b || 'B';
  const all = A.concat(B);
  if (all.length < 2) { host.innerHTML = '<p class="muted">数据不足，无法绘制对比走势。</p>'; return; }

  const W = Math.max(360, host.clientWidth || 700), H = 340;
  const L = 48, R = 16, T = 16, Bm = 30;
  const iW = W - L - R, iH = H - T - Bm;
  const times = all.map(d => d.time), rs = all.map(d => d.new_rating);
  let xMin = Math.min(...times), xMax = Math.max(...times); if (xMax === xMin) xMax = xMin + 1;
  let yMin = Math.floor((Math.min(...rs) - 60) / 100) * 100;
  let yMax = Math.ceil((Math.max(...rs) + 60) / 100) * 100;
  yMin = Math.max(0, yMin); if (yMax - yMin < 200) yMax = yMin + 200;
  const X = t => L + ((t - xMin) / (xMax - xMin)) * iW;
  const Y = r => T + (1 - (r - yMin) / (yMax - yMin)) * iH;

  let svg = `<svg class="rc-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for (const [lo, hi, col] of RC_BANDS) {           // 等级色带
    if (hi <= yMin || lo >= yMax) continue;
    const top = Y(Math.min(hi, yMax)), bot = Y(Math.max(lo, yMin));
    svg += `<rect class="rc-band" x="${L}" y="${top.toFixed(1)}" width="${iW}" height="${(bot - top).toFixed(1)}" fill="${col}"/>`;
  }
  const range = yMax - yMin;
  const step = range <= 600 ? 100 : range <= 1200 ? 200 : range <= 2400 ? 400 : 600;
  for (let r = yMin; r <= yMax; r += step) {        // 横向网格 + Y 轴
    const y = Y(r);
    svg += `<line class="rc-grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    svg += `<text class="rc-axis" x="${L - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${r}</text>`;
  }
  const ticks = 5;
  for (let k = 0; k < ticks; k++) {                 // X 轴日期
    const t = xMin + (xMax - xMin) * k / (ticks - 1);
    const dt = new Date(t * 1000);
    svg += `<text class="rc-axis" x="${X(t).toFixed(1)}" y="${H - 10}" text-anchor="middle">${dt.getFullYear()}/${String(dt.getMonth() + 1).padStart(2, '0')}</text>`;
  }
  svg += vsSeries(A, X, Y, VS_A, 'a');
  svg += vsSeries(B, X, Y, VS_B, 'b');
  svg += `</svg>`;
  host.innerHTML = svg;

  host.querySelectorAll('.vs-dot').forEach(dot => {
    dot.addEventListener('mouseenter', e => {
      const who = e.target.dataset.s, i = +e.target.dataset.i;
      vsShowTip(e.target, (who === 'a' ? A : B)[i], who === 'a' ? hA : hB, who === 'a' ? VS_A : VS_B);
    });
    dot.addEventListener('mouseleave', rcHideTip);
  });
}

function vsSeries(data, X, Y, color, who) {
  if (!data.length) return '';
  const pts = data.map(d => [X(d.time), Y(d.new_rating)]);
  let s = '';
  if (pts.length >= 2) {
    const line = 'M' + pts.map(p => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L ');
    s += `<path d="${line}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  data.forEach((d, i) => {
    s += `<circle class="vs-dot" cx="${pts[i][0].toFixed(1)}" cy="${pts[i][1].toFixed(1)}" r="3.2" fill="${color}" stroke="var(--bg-elev)" stroke-width="1.2" data-s="${who}" data-i="${i}"/>`;
  });
  return s;
}

function vsShowTip(dot, d, handle, color) {
  const t = _rcTip();
  const dt = new Date(d.time * 1000);
  const ds = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  const up = d.rating_change > 0;
  t.innerHTML = `<span class="rc-tt-name" style="color:${color};">${rcEsc(handle)}</span>`
    + `${rcEsc(d.name)}<br>排名 #${d.rank}<br>${d.old_rating} → <b>${d.new_rating}</b> `
    + `<span style="color:${up ? '#2ecc71' : '#e74c3c'};font-weight:700;">(${up ? '+' : ''}${d.rating_change})</span><br>`
    + `<span style="opacity:.65;">${ds}</span>`;
  t.style.display = 'block';
  const r = dot.getBoundingClientRect();
  const tw = t.offsetWidth, th = t.offsetHeight;
  const left = Math.max(8, Math.min(r.left + r.width / 2 - tw / 2, window.innerWidth - tw - 8));
  let top = r.top - th - 10; if (top < 8) top = r.bottom + 10;
  t.style.left = left + 'px'; t.style.top = top + 'px';
}

document.addEventListener('DOMContentLoaded', () => {
  const a = document.getElementById('vsA'), b = document.getElementById('vsB');
  document.querySelectorAll('.pick-army').forEach(chip => {
    chip.onclick = () => {
      const h = chip.dataset.h;
      if (!a.value.trim()) a.value = h;
      else if (!b.value.trim()) b.value = h;
      else toast('A、B 都已填，先清空一个再选', 'info');
    };
  });
  const form = document.getElementById('vsForm');
  if (form) form.addEventListener('submit', () => { markNav(); showOverlay('正在对比两位选手…'); });

  document.querySelectorAll('.vs-chart').forEach(renderVsChart);
  let rz;
  window.addEventListener('resize', () => {
    clearTimeout(rz);
    rz = setTimeout(() => document.querySelectorAll('.vs-chart').forEach(renderVsChart), 200);
  });
});
