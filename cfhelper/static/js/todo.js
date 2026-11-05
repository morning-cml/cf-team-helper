'use strict';
/* 题单页：完成 / 移除 / 清空已完成。依赖 app.js 的全局 toast() / markNav()。 */

function _todoAction(url, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  fetch(url, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      toast(d.msg, d.success ? 'ok' : 'err');
      if (d.success) { markNav(); setTimeout(() => location.reload(), 400); }
    })
    .catch(() => toast('操作失败', 'err'));
}

function todoToggle(key)  { _todoAction('/api/todo/toggle?key=' + encodeURIComponent(key)); }
function todoRemove(key)  { _todoAction('/api/todo/remove?key=' + encodeURIComponent(key)); }
function todoClearDone()  { _todoAction('/api/todo/clear_done', '清空所有已完成的题？'); }
