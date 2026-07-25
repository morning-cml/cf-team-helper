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
        text.textContent = `已抓 ${st.done}/${st.total} 场（成功 ${st.ok}）· 约剩 ${Math.ceil(left * 1.8 / 60)} 分钟`;
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
