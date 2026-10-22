'use strict';

const TTL_MS = 10 * 60 * 1000;
function callbackForFlow(raw, flow, sid, now = Date.now()) {
  const fail = (message, statusCode = 400) => { throw Object.assign(new Error(message), { statusCode }); };
  if (!flow || !flow.cloud || flow.ownerSid !== sid) fail('授权流程不存在或不属于当前登录会话', 404);
  if (now - flow.createdAt >= TTL_MS) fail('授权流程已过期，请重新开始');
  if (typeof raw !== 'string' || raw.length > 16384) fail('请粘贴完整的官方回调链接');
  let u;
  try { u = new URL(raw.trim()); } catch { fail('请粘贴完整的官方回调链接'); }
  const official = u.origin === 'https://irisgo.ai' && u.pathname === '/oauth/google';
  const desktop = ['irisgo:', 'ai.irisgo:'].includes(u.protocol) && u.hostname === 'oauth' && u.pathname === '/callback';
  if ((!official && !desktop) || u.username || u.password || u.port || u.hash) fail('仅接受 IrisGo 官方授权回调链接');
  if (!flow.state || u.searchParams.getAll('state').length !== 1 || u.searchParams.get('state') !== flow.state) {
    fail('回调状态不匹配，请使用本页生成的 Google 授权链接');
  }
  if (u.searchParams.has('error')) fail('Google 授权未完成或已取消，请重新开始');
  if (u.searchParams.getAll('code').length !== 1 || !u.searchParams.get('code') || u.searchParams.get('code').length > 8192) {
    fail('回调链接缺少有效授权码');
  }
  return u.href;
}

module.exports = { TTL_MS, callbackForFlow };
