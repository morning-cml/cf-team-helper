'use strict';
/* ICPC 比赛库：档位 / 年份 / 关键词 / 只看做过的 —— 四个条件在客户端组合筛选。
   160 场全部随页面渲染，筛选纯前端完成，不再打服务端。
   依赖 app.js 的全局 toast() / markNav() / showOverlay()。 */

function icpcFilter() {
  const tierChip = document.querySelector('#icpcTierFilter .chip.active');
  const tier = tierChip ? tierChip.dataset.tier : 'all';
  const year = document.getElementById('icpcYear').value;
  const kw = document.getElementById('icpcSearch').value.trim().toLowerCase();
  const onlyDone = document.getElementById('icpcOnlyDone');
  const doneOnly = onlyDone && onlyDone.checked;

  let shown = 0;
  document.querySelectorAll('.icpc-item').forEach(it => {
    const d = it.dataset;
    const ok = (tier === 'all' || d.tier === tier)
      && (year === 'all' || d.year === year)
      && (!kw || d.name.includes(kw))
      && (!doneOnly || d.done === '1');
    it.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });

  // 整组都被筛掉时把这一档的卡片也收起来，避免留下空标题
  document.querySelectorAll('.icpc-group').forEach(g => {
    const any = Array.from(g.querySelectorAll('.icpc-item')).some(i => i.style.display !== 'none');
    g.style.display = any ? '' : 'none';
  });

  const label = document.getElementById('icpcCount');
  if (label) label.textContent = `当前显示 ${shown} 场`;
}

/* ==================== 抽一场来练 ==================== */
function icpcEsc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function icpcDraw(btn) {
  const tier = document.getElementById('drawTier').value;
  const input = document.getElementById('icpcInput');
  const params = new URLSearchParams({ tier, handles: input ? input.value : '' });
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 抽取中…'; }
  fetch('/api/icpc/draw?' + params.toString(), { method: 'POST' })
    .then(r => r.json())
    .then(d => icpcRenderDraw(d))
    .catch(() => toast('抽取失败', 'err'))
    .finally(() => { if (btn) { btn.disabled = false; btn.textContent = '🎲 抽取'; } });
}

function icpcRenderDraw(d) {
  const box = document.getElementById('drawResult');
  const i = d.info || {};
  if (!d.success) {
    box.innerHTML = `<div class="draw-empty">${icpcEsc(d.msg || '没有可抽的比赛')}</div>`;
    return;
  }
  const c = d.contest, p = d.progress;
  // 说明这次是从哪个池子里抽的，避免"为什么老抽到做过的"之类的困惑
  const from = i.source === 'fresh'
    ? `从 <b>${i.fresh}</b> 场一题都没解出的比赛中抽取`
    : `该档每场都解出过题，从 <b>${i.partial}</b> 场未超 ${i.skip_rate}% 的比赛中抽取`;
  const skipped = i.mastered ? ` · 已排除 ${i.mastered} 场解出超 ${i.skip_rate}% 的` : '';

  let grid = '';
  if (p && p.problems) {
    grid = '<div class="icpc-probs" style="padding-left:0;margin-top:8px;">'
      + p.problems.map(q => `<a class="pq pq-${q.state}" href="${q.url}" target="_blank"`
        + ` title="${icpcEsc(q.i + '. ' + (q.n || '（题名未知）'))}">${icpcEsc(q.i)}</a>`).join('')
      + '</div>';
  }
  let done;
  if (!p) done = '<b>还没碰过这场</b>（题单未知）';
  else if (!p.count) done = `<b>全新的一场</b>${p.total ? ` · 共 ${p.total} 题` : ''}`;
  else if (p.total) done = `已解出 <b>${p.count}/${p.total}</b>（${p.pct}%）`;
  else done = `已解出 <b>${p.count}</b> 题`;

  box.innerHTML = `
    <div class="draw-card">
      <div class="draw-meta">
        <span class="tier-badge ${c.tier_cls}">${icpcEsc(c.tier_name)}</span>
        <span class="muted">${c.year || ''} · ${c.gym ? 'Gym' : '官方'}</span>
        <span class="muted">${from}${skipped}</span>
      </div>
      <a class="draw-name" href="${c.url}" target="_blank">${icpcEsc(c.name)}</a>
      <div class="draw-done">${done}</div>
      ${grid}
    </div>`;
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ==================== 题单抓取：后台跑，前端轮询进度 ==================== */
function icpcPollFetch() {
  fetch('/api/icpc/fetch_state')
    .then(r => r.json())
    .then(st => {
      const box = document.getElementById('icpcFetchProgress');
      const fill = document.getElementById('icpcFetchFill');
      const text = document.getElementById('icpcFetchText');
      if (!box) return;
      if (st.running) {
        box.style.display = '';
        const pct = st.total ? Math.round(st.done / st.total * 100) : 0;
        fill.style.width = pct + '%';
        const left = st.total - st.done;
        // 两段的速度差一个量级，分别按各自的速率估剩余时间，否则第二段会显得"卡住"
        const perSec = st.phase === 'medals' ? 4.5 : 1.8;
        const label = st.phase === 'medals' ? '第 2/2 段 · 抓奖牌线（榜单较大，较慢）'
          : '第 1/2 段 · 抓题单';
        text.textContent = `${label}：${st.done}/${st.total} 场（成功 ${st.ok}）`
          + ` · 约剩 ${Math.ceil(left * perSec / 60)} 分钟`;
        setTimeout(icpcPollFetch, 2000);
      } else if (box.style.display !== 'none') {
        fill.style.width = '100%';
        text.textContent = `抓取完成，题单已覆盖 ${st.covered}/${st.total_contests} 场，正在刷新…`;
        toast('题单抓取完成', 'ok');
        markNav();
        setTimeout(() => location.reload(), 1200);
      }
    })
    .catch(() => { /* 轮询失败就安静停下，不打扰用户 */ });
}

function icpcFetch(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 抓取中…'; }
  fetch('/api/icpc/fetch_problems', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (!d.success) { toast(d.msg, 'err'); if (btn) { btn.disabled = false; btn.textContent = '📥 抓取题单'; } return; }
      toast(d.msg, 'ok');
      document.getElementById('icpcFetchProgress').style.display = '';
      icpcPollFetch();
    })
    .catch(() => { toast('启动抓取失败', 'err'); if (btn) btn.disabled = false; });
}

function icpcRefresh(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 重拉中…'; }
  fetch('/api/icpc/refresh', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      toast(d.msg, d.success ? 'ok' : 'err');
      if (d.success) { markNav(); setTimeout(() => location.reload(), 700); }
    })
    .catch(() => toast('刷新失败', 'err'))
    .finally(() => { if (btn) { btn.disabled = false; btn.textContent = '🔄 重拉比赛库'; } });
}

document.addEventListener('DOMContentLoaded', () => {
  const tf = document.getElementById('icpcTierFilter');
  if (tf) {
    tf.querySelectorAll('.chip').forEach(chip => {
      chip.onclick = () => {
        tf.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        icpcFilter();
      };
    });
  }
  ['icpcYear', 'icpcSearch', 'icpcOnlyDone'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(el.tagName === 'INPUT' && el.type === 'text' ? 'input' : 'change', icpcFilter);
  });

  const input = document.getElementById('icpcInput');
  document.querySelectorAll('.pick-army').forEach(chip => {
    chip.onclick = () => {
      const h = chip.dataset.h;
      const cur = input.value.split(/[,，]/).map(x => x.trim()).filter(Boolean);
      if (cur.map(x => x.toLowerCase()).includes(h.toLowerCase())) {
        toast(h + ' 已在列表中', 'info');
        return;
      }
      cur.push(h);
      input.value = cur.join(', ');
    };
  });

  const form = document.getElementById('icpcForm');
  if (form) form.addEventListener('submit', () => { markNav(); showOverlay('正在比对做题记录…'); });

  icpcFilter();

  // 页面打开时若后台抓取仍在跑（例如上次点了抓取后跳走又回来），自动接上进度
  if (document.getElementById('icpcFetchProgress')) icpcPollFetch();
});
