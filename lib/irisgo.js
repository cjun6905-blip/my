'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');
const crypto = require('node:crypto');
const { b64urlJson, nowSec } = require('./util');
const { agentFor } = require('./proxies');

const API_HOST = 'api.irisgo.ai';

function decodeJwt(token) {
  if (!token || typeof token !== 'string') return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const header = b64urlJson(parts[0]);
  const payload = b64urlJson(parts[1]);
  if (!payload) return null;
  return { header, payload, signature: parts[2] };
}

function describeToken(token) {
  const decoded = decodeJwt(token);
  if (!decoded) return { valid: false };
  const p = decoded.payload;
  return {
    valid: true,
    userId: p.user_id || p.sub || '',
    email: p.email || '',
    provider: p.provider || '',
    kind: p.kind || '',
    issuer: p.iss || '',
    exp: p.exp || 0,
    iat: p.iat || 0,
    expired: p.exp ? p.exp * 1000 < Date.now() : false,
  };
}

function localProfilesDir() {
  const base = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  return path.join(base, 'IrisGo', 'profiles');
}

function activeUserId() {
  const base = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(base, 'IrisGo', 'current-user.json'), 'utf8'));
    return raw.user_id || null;
  } catch {
    return null;
  }
}

function readSecrets(dbPath) {
  const { DatabaseSync } = require('node:sqlite');
  const dir = path.dirname(dbPath);
  const tmpBase = path.join(os.tmpdir(), 'igp-sqlite-' + crypto.randomBytes(6).toString('hex'));
  const copies = [];
  try {
    for (const suffix of ['', '-wal', '-shm']) {
      const src = dbPath + suffix;
      if (fs.existsSync(src)) {
        const dst = tmpBase + suffix;
        fs.copyFileSync(src, dst);
        copies.push(dst);
      }
    }
    const db = new DatabaseSync(tmpBase);
    try {
      const rows = db.prepare('SELECT key, value FROM secrets').all();
      const out = {};
      for (const row of rows) out[row.key] = row.value;
      return out;
    } finally {
      db.close();
    }
  } finally {
    for (const file of copies) {
      try {
        fs.unlinkSync(file);
      } catch {}
    }
  }
}

function scanLocalAccounts() {
  const dir = localProfilesDir();
  const result = { dir, exists: fs.existsSync(dir), activeUserId: activeUserId(), accounts: [], errors: [] };
  if (!result.exists) return result;
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory());
  } catch (err) {
    result.errors.push({ path: dir, error: err.message });
    return result;
  }
  for (const entry of entries) {
    const profileDir = path.join(dir, entry.name);
    const dbPath = path.join(profileDir, 'data', 'app.sqlite');
    if (!fs.existsSync(dbPath)) continue;
    try {
      const secrets = readSecrets(dbPath);
      const raw = secrets['auth.irisgo'];
      if (!raw) continue;
      const session = JSON.parse(raw);
      if (!session || !session.token) continue;
      const info = describeToken(session.token);
      result.accounts.push({
        profileId: entry.name,
        profilePath: profileDir,
        userId: info.userId || entry.name,
        email: info.email || '',
        token: session.token,
        refreshToken: session.refresh_token || '',
        exp: info.exp || 0,
        isActive: entry.name === result.activeUserId,
        valid: info.valid && !info.expired,
      });
    } catch (err) {
      result.errors.push({ path: dbPath, error: err.message });
    }
  }
  return result;
}

function requestJson({ method = 'GET', path: urlPath, body, token, proxy, timeoutMs = 30000 }) {
  return new Promise((resolve, reject) => {
    const payload = body ? Buffer.from(JSON.stringify(body)) : null;
    const agent = agentFor(proxy);
    const req = https.request(
      {
        host: API_HOST,
        port: 443,
        method,
        path: urlPath,
        agent: agent || undefined,
        servername: API_HOST,
        headers: {
          Accept: 'application/json',
          'User-Agent': 'IrisGoProxy/1.0',
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
          ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}),
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
    req.setTimeout(timeoutMs, () => req.destroy(new Error('请求 IrisGo 接口超时')));
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function fetchProfile(token, proxy) {
  const res = await requestJson({ path: '/auth/profile', token, proxy });
  if (res.status !== 200) {
    throw new Error(`账号校验失败（HTTP ${res.status}）${typeof res.data === 'string' ? ': ' + res.data.slice(0, 120) : ''}`);
  }
  return res.data;
}

async function refreshSession(refreshToken, proxy) {
  const res = await requestJson({
    method: 'POST',
    path: '/auth/refresh',
    body: { refresh_token: refreshToken },
    proxy,
  });
  if (res.status !== 200) {
    throw new Error(`刷新失败（HTTP ${res.status}）${typeof res.data === 'string' ? ': ' + res.data.slice(0, 120) : ''}`);
  }
  const data = res.data || {};
  const token = data.token || data.access_token;
  if (!token) throw new Error('刷新接口没有返回 access token');
  return {
    token,
    refreshToken: data.refresh_token || refreshToken,
    info: describeToken(token),
    raw: data,
  };
}

async function exchangeGoogleCode(code, proxy) {
  const res = await requestJson({
    method: 'POST',
    path: '/auth/callback/google',
    body: { code },
    proxy,
  });
  if (res.status !== 200) {
    const detail = typeof res.data === 'string' ? res.data : res.data?.error || res.text || '';
    throw new Error(
      `Google 授权码兑换失败（HTTP ${res.status}）${detail ? '：' + String(detail).slice(0, 180) : ''}`
    );
  }
  const data = res.data || {};
  const session = data.session || data.data || data;
  const token = session.token || session.access_token || data.token;
  if (!token) throw new Error('兑换接口没有返回 token');
  return {
    token,
    refreshToken: session.refresh_token || session.refreshToken || data.refresh_token || '',
    user: session.user || data.user || null,
    info: describeToken(token),
    raw: data,
  };
}

function accountView(account, { withToken = false } = {}) {
  const view = {
    id: account.id,
    label: account.label,
    email: account.email,
    userId: account.userId,
    proxy: account.proxy || '',
    enabled: !!account.enabled,
    weight: account.weight || 1,
    status: account.status || 'ok',
    lastError: account.lastError || '',
    cooldownUntil: account.cooldownUntil || 0,
    needsRelogin: !!account.needsRelogin,
    source: account.source || 'manual',
    exp: account.exp || 0,
    createdAt: account.createdAt,
    updatedAt: account.updatedAt,
    stats: account.stats,
  };
  if (withToken) {
    view.token = account.token;
    view.refreshToken = account.refreshToken;
  }
  return view;
}

function tokenExpiryText(exp) {
  if (!exp) return '未知';
  const d = new Date(exp * 1000);
  return d.toISOString().slice(0, 10);
}

function isExpiringSoon(exp, days = 7) {
  if (!exp) return false;
  return exp * 1000 - Date.now() < days * 86400 * 1000;
}

module.exports = {
  API_HOST,
  decodeJwt,
  describeToken,
  scanLocalAccounts,
  localProfilesDir,
  activeUserId,
  fetchProfile,
  refreshSession,
  exchangeGoogleCode,
  requestJson,
  accountView,
  tokenExpiryText,
  isExpiringSoon,
  nowSec,
};
