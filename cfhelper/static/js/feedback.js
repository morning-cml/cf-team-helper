'use strict';
/* 反馈页：把表单拼成 issue 正文，生成预填链接交给用户自己提交。
   这里不发送任何东西，也没有任何凭据——见 config.REPO_URL 上的说明。
   依赖 app.js 的全局 toast()。 */

const FB_OPEN_AT = Date.now();
let fbKind = 'bug', fbLabel = 'bug';

function fbDiag() {
  let d = {};
  try { d = JSON.parse(document.getElementById('fbDiag').textContent); } catch (e) {}
  const mins = Math.round((Date.now() - FB_OPEN_AT) / 60000);
  const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? '深色' : '浅色';
  // 只列排查用得上、且与身份无关的项。navigator.userAgent 会带出浏览器与操作系统版本，
  // 这是定位渲染 / 定时器类问题的关键，但不含任何账号信息。
  return [
    `- 程序版本：v${d.version || '?'}`,
    `- 出问题的页面：${document.getElementById('fbPage').value || '（未指定）'}`,
    `- 浏览器：${navigator.userAgent}`,
    `- 主题：${theme}`,
    `- 是否配置 CF API 密钥：${d.has_key || '?'}`,
    `- ICPC 比赛库：${d.contests || 0} 场 ｜ 题单 ${d.problems || '?'} ｜ 奖牌线 ${d.medals || '?'}`,
    `- 本页已打开：${mins} 分钟`,
  ].join('\n');
}

function fbBody() {
  const desc = document.getElementById('fbDesc').value.trim();
  const steps = document.getElementById('fbSteps').value.trim();
  const head = fbKind === 'feat' ? '## 想要的功能'
    : fbKind === 'ask' ? '## 我的疑问' : '## 问题描述';
  let s = `${head}\n\n${desc || '（未填写）'}\n`;
  if (steps) s += `\n## 复现步骤\n\n${steps}\n`;
  s += '\n---\n\n<details><summary>环境信息（程序自动收集，不含账号 / 用户名 / 密钥 / 本地路径）</summary>\n\n'
    + fbDiag() + '\n\n</details>\n';
  return s;
}

let _fbTouched = false;   // 用户改过正文后就不再自动覆盖，免得辛苦编辑被冲掉

function fbRefresh() {
  if (_fbTouched) { fbUpdateLen(); return; }
  document.getElementById('fbPreview').value = fbBody();
  fbUpdateLen();
}

function fbUpdateLen() {
  const body = document.getElementById('fbPreview').value;
  const title = document.getElementById('fbTitle').value.trim();
  const url = fbUrl(title, body);
  const el = document.getElementById('fbLen');
  if (url.length > FB_URL_LIMIT) {
    el.innerHTML = `⚠️ 内容偏长（链接 ${url.length} 字符，超过 ${FB_URL_LIMIT}），`
      + '浏览器可能截断。建议用「📋 复制全文」，到 GitHub 上手动粘贴。';
    el.style.color = 'var(--danger)';
  } else {
    el.textContent = `正文 ${body.length} 字符`;
    el.style.color = '';
  }
}

function fbUrl(title, body) {
  const p = new URLSearchParams({ title: title, body: body, labels: fbLabel });
  return `${FB_REPO}/issues/new?${p.toString()}`;
}

function fbSubmit(btn) {
  const title = document.getElementById('fbTitle').value.trim();
  if (!title) { toast('请先填一句话标题', 'err'); document.getElementById('fbTitle').focus(); return; }
  const body = document.getElementById('fbPreview').value;
  const url = fbUrl(title, body);
  if (url.length > FB_URL_LIMIT) {
    toast('内容太长，请改用「复制全文」再到 GitHub 粘贴', 'err');
    return;
  }
  markNav();                      // 这是站外新标签，但顺手标记，避免被当成关页
  window.open(url, '_blank');
  toast('已打开 GitHub，请在那边点 Submit 完成提交', 'ok');
}

function fbCopy(btn) {
  const title = document.getElementById('fbTitle').value.trim();
  const text = (title ? `标题：${title}\n\n` : '') + document.getElementById('fbPreview').value;
  navigator.clipboard.writeText(text)
    .then(() => toast('已复制，可粘贴到 GitHub issue 或发给作者', 'ok'))
    .catch(() => toast('复制失败，请手动全选文本框内容', 'err'));
}

document.addEventListener('DOMContentLoaded', () => {
  const kinds = document.getElementById('fbKind');
  kinds.querySelectorAll('.chip').forEach(chip => {
    chip.onclick = () => {
      kinds.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      fbKind = chip.dataset.kind;
      fbLabel = chip.dataset.label;
      // 只有 Bug 才需要复现步骤，其它类型收起来减少干扰
      document.getElementById('fbStepsBox').style.display = fbKind === 'bug' ? '' : 'none';
      fbRefresh();
    };
  });
  ['fbTitle', 'fbDesc', 'fbSteps', 'fbPage'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', fbRefresh);
    if (el && el.tagName === 'SELECT') el.addEventListener('change', fbRefresh);
  });
  document.getElementById('fbPreview').addEventListener('input', () => { _fbTouched = true; fbUpdateLen(); });
  fbRefresh();
});
