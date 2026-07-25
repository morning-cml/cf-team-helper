'use strict';
/* 组队作战：大部队 chip 快速填入 + 提交时遮罩。
   依赖 app.js 提供的全局 toast() / markNav() / showOverlay()。 */

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('teamInput');

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

  const form = document.getElementById('teamForm');
  if (form) form.addEventListener('submit', () => { markNav(); showOverlay('正在分析队伍，请稍候…'); });
});
