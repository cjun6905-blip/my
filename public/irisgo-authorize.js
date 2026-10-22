'use strict';
const el = (id) => document.getElementById(id);
let flow = null;
const message = (text) => { el('auth-status').textContent = text; };
async function api(path, body) {
  const res = await fetch(path, { credentials: 'same-origin', cache: 'no-store',
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-IGP-Request': '1', 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await res.json();
  if (res.status === 401 || res.status === 403) throw new Error('请先在管理面板使用管理员令牌登录，再返回此页');
  if (!res.ok || data.ok === false) throw new Error(data.error?.message || data.error || '请求失败，请稍后重试');
  return data;
}
async function boot() {
  const me = await api('/api/me');
  if (me.role !== 'admin') throw new Error('仅管理员可添加上游账号');
  const data = await api('/api/accounts');
  const used = new Set(data.accounts.map((a) => a.proxySlotId));
  const slots = data.proxySlots || [];
  el('auth-proxy').add(new Option('直连（不使用代理）', ''));
  for (const slot of slots) {
    const option = new Option(slot.name + (slot.enabled ? '' : '（停用）'), slot.id);
    option.disabled = !slot.enabled;
    el('auth-proxy').add(option);
  }
  const preferred = slots.find((s) => s.enabled && !used.has(s.id)) || slots.find((s) => s.enabled);
  el('auth-proxy').value = preferred?.id || '';
  el('auth-proxy').disabled = false;
  el('auth-start').disabled = false;
  message('管理员已登录。请先选节点，再生成 Google 授权链接。');
}
el('start-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (flow && !confirm('重新生成后请只使用新链接。确定重新开始吗？')) return;
  el('auth-start').disabled = true;
  el('auth-complete').disabled = true;
  el('auth-flow').classList.add('hidden');
  el('auth-callback').value = '';
  flow = null;
  try {
    const result = await api('/api/oauth/web/start', { mode: 'cloud', proxySlotId: el('auth-proxy').value, proxy: '' });
    const url = new URL(result.url);
    if (url.origin !== 'https://api.irisgo.ai' || url.pathname !== '/auth/google') throw new Error('授权链接异常，请联系管理员');
    flow = result;
    el('google-authorize').href = result.url;
    el('auth-expiry').textContent = '本次授权有效至 ' + new Date(result.expiresAt).toLocaleTimeString();
    el('auth-flow').classList.remove('hidden');
    el('auth-complete').disabled = false;
    message('链接已生成。请在官方页面授权，然后返回此页粘贴回调链接。');
  } catch (err) { message(err.message); }
  finally { el('auth-start').disabled = false; }
});
el('complete-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!flow || Date.now() >= flow.expiresAt) return message('流程不存在或已过期，请重新生成授权链接。');
  el('auth-complete').disabled = true;
  try {
    const result = await api('/api/oauth/web/complete', { flowId: flow.flowId, callbackUrl: el('auth-callback').value.trim() });
    el('auth-callback').value = '';
    flow = null;
    el('auth-flow').classList.add('hidden');
    message('授权成功，账号已保存' + (result.email ? '：' + result.email : '') + '。可返回账号池测试连接。');
  } catch (err) { message(err.message); el('auth-complete').disabled = false; }
});
boot().catch((err) => message(err.message));
