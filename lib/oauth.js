'use strict';

const https = require('node:https');
const crypto = require('node:crypto');
const { b64urlDecode, b64urlJson } = require('./util');
const { agentFor } = require('./proxies');

const AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth';
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token';
const JWKS_ENDPOINT = 'https://www.googleapis.com/oauth2/v3/certs';

const jwksCache = { keys: null, fetchedAt: 0 };

function httpJson({ method = 'GET', url, headers = {}, body = null, proxy = '', timeoutMs = 20000 }) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const payload = body ? Buffer.from(body) : null;
    const agent = agentFor(proxy);
    const req = https.request(
      {
        host: u.hostname,
        port: 443,
        method,
        path: u.pathname + u.search,
        agent: agent || undefined,
        servername: u.hostname,
        headers: {
          Accept: 'application/json',
          'User-Agent': 'IrisGoProxy/1.0',
          ...(payload ? { 'Content-Length': payload.length } : {}),
          ...headers,
        },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let data = null;
          try {
            data = text ? JSON.parse(text) : null;
          } catch {
            data = text;
          }
          resolve({ status: res.statusCode, headers: res.headers, data, text });
        });
        res.on('error', reject);
      }
    );
    req.setTimeout(timeoutMs, () => req.destroy(new Error('Google 接口超时')));
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function buildAuthUrl(cfg, redirectUri, state) {
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state,
    access_type: 'online',
    prompt: 'select_account',
    include_granted_scopes: 'true',
  });
  return AUTH_ENDPOINT + '?' + params.toString();
}

async function exchangeCode(cfg, code, redirectUri) {
  const body = new URLSearchParams({
    code,
    client_id: cfg.clientId,
    client_secret: cfg.clientSecret,
    redirect_uri: redirectUri,
    grant_type: 'authorization_code',
  }).toString();
  const res = await httpJson({
    method: 'POST',
    url: TOKEN_ENDPOINT,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
    proxy: cfg.proxy || '',
  });
  if (res.status !== 200) {
    const detail = res.data?.error_description || res.data?.error || res.text?.slice(0, 200) || '';
    throw new Error(`Google 换取 token 失败（HTTP ${res.status}）${detail ? '：' + detail : ''}`);
  }
  return res.data;
}

async function getJwks(proxy) {
  if (jwksCache.keys && Date.now() - jwksCache.fetchedAt < 3600_000) return jwksCache.keys;
  const res = await httpJson({ url: JWKS_ENDPOINT, proxy });
  if (res.status !== 200 || !res.data?.keys) throw new Error('无法获取 Google 公钥');
  jwksCache.keys = res.data.keys;
  jwksCache.fetchedAt = Date.now();
  return jwksCache.keys;
}

async function verifyIdToken(idToken, clientId, proxy) {
  const parts = String(idToken || '').split('.');
  if (parts.length !== 3) throw new Error('id_token 格式不正确');
  const header = b64urlJson(parts[0]);
  const payload = b64urlJson(parts[1]);
  if (!header || !payload) throw new Error('id_token 解析失败');

  if (payload.aud !== clientId) throw new Error('id_token 的 aud 不匹配');
  const iss = String(payload.iss || '');
  if (iss !== 'accounts.google.com' && iss !== 'https://accounts.google.com') {
    throw new Error('id_token 的 iss 不正确');
  }
  if (payload.exp && payload.exp * 1000 < Date.now()) throw new Error('id_token 已过期');

  const keys = await getJwks(proxy);
  const jwk = keys.find((k) => k.kid === header.kid) || keys[0];
  if (!jwk) throw new Error('找不到匹配的 Google 公钥');

  const publicKey = crypto.createPublicKey({ key: { kty: jwk.kty, n: jwk.n, e: jwk.e }, format: 'jwk' });
  const ok = crypto.verify(
    'RSA-SHA256',
    Buffer.from(parts[0] + '.' + parts[1]),
    publicKey,
    b64urlDecode(parts[2])
  );
  if (!ok) throw new Error('id_token 签名校验失败');
  return payload;
}

function isAllowed(cfg, email) {
  const list = (cfg.allowedEmails || []).map((s) => String(s).trim().toLowerCase()).filter(Boolean);
  const domains = (cfg.allowedDomains || []).map((s) => String(s).trim().toLowerCase()).filter(Boolean);
  if (!list.length && !domains.length) return true;
  const lower = String(email || '').toLowerCase();
  if (list.includes(lower)) return true;
  const domain = lower.split('@')[1] || '';
  return domains.includes(domain);
}

module.exports = { buildAuthUrl, exchangeCode, verifyIdToken, isAllowed, httpJson };
