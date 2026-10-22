'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');

const { Store } = require('./lib/store');
const { Pool } = require('./lib/pool');
const upstream = require('./lib/upstream');
const irisgo = require('./lib/irisgo');
const oauth = require('./lib/oauth');
const models = require('./lib/models');
const util = require('./lib/util');
const { TTL_MS: IRISGO_LOGIN_TTL, callbackForFlow } = require('./lib/irisgo-login');

const ROOT = __dirname;
const DATA_DIR = path.resolve(process.env.IGP_DATA_DIR || path.join(ROOT, 'data'));
const PUBLIC_DIR = path.join(ROOT, 'public');
const CONFIG_PATH = path.join(DATA_DIR, 'config.json');
const { ProxySlots } = require('./lib/proxy-slots');
const proxySlots = new ProxySlots(process.env.IGP_PROXY_SLOTS || path.join(DATA_DIR, 'proxy-slots.private.json'));
const LOG_PATH = path.join(DATA_DIR, 'proxy.log');
const SECRET_PATH = path.join(DATA_DIR, 'deeplink-secret.txt');
const QUEUE_PATH = path.join(DATA_DIR, 'deeplink-queue.jsonl');
const VERSION = '1.1.0';

fs.mkdirSync(DATA_DIR, { recursive: true });
const log = util.createLogger(LOG_PATH);
const store = new Store(CONFIG_PATH);
const boot = store.load();
const pool = new Pool(store, log);

try {
  fs.writeFileSync(SECRET_PATH, store.data.deeplink.secret + '\n', 'utf8');
} catch {}

const sessions = new Map();
const oauthStates = new Map();
const rateBuckets = new Map();
const loginFlows = new Map();

const SESSION_TTL_MS = 7 * 86400 * 1000;
const STATE_TTL_MS = 10 * 60 * 1000;

function publicBaseUrl() {
  const configured = (store.data.server.publicBaseUrl || '').trim().replace(/\/+$/, '');
  if (configured) return configured;
  const host = store.data.server.host === '0.0.0.0' ? '127.0.0.1' : store.data.server.host;
  return `http://${host}:${store.data.server.port}`;
}

/* --------------------------- irisgo:// deep link --------------------------- */

function deeplinkVbsPath() {
  return path.join(ROOT, 'lib', 'deeplink.vbs');
}

function writeDeeplinkVbs() {
  const nodeExe = process.execPath;
  const script = path.join(ROOT, 'lib', 'deeplink.js');
  const vbs = [
    'Dim sh, u, q',
    'If WScript.Arguments.Count = 0 Then WScript.Quit 0',
    'u = WScript.Arguments(0)',
    'q = Chr(34)',
    'Set sh = CreateObject("WScript.Shell")',
    `sh.Run q & "${nodeExe}" & q & " " & q & "${script}" & q & " " & q & u & q, 0, False`,
    '',
  ].join('\r\n');
  fs.writeFileSync(deeplinkVbsPath(), vbs, 'ascii');
  return deeplinkVbsPath();
}

function readRegisteredCommand(scheme) {
  try {
    const out = execFileSync('reg', ['query', `HKCU\\Software\\Classes\\${scheme}\\shell\\open\\command`, '/ve'], {
      encoding: 'utf8',
      windowsHide: true,
    });
    const line = out.split(/\r?\n/).find((l) => l.includes('REG_SZ'));
    return line ? line.split('REG_SZ')[1].trim() : '';
  } catch {
    return '';
  }
}

function ensureScheme() {
  const scheme = store.data.deeplink.scheme || 'irisgo';
  const vbs = writeDeeplinkVbs();
  const wscript = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'wscript.exe');
  const command = `"${wscript}" //nologo "${vbs}" "%1"`;
  const current = readRegisteredCommand(scheme);
  if (current === command) {
    return { ok: true, command, changed: false };
  }
  try {
    execFileSync('reg', ['add', `HKCU\\Software\\Classes\\${scheme}`, '/ve', '/d', 'URL:IrisGo Proxy OAuth', '/f'], {
      windowsHide: true,
    });
    execFileSync('reg', ['add', `HKCU\\Software\\Classes\\${scheme}`, '/v', 'URL Protocol', '/d', '', '/f'], {
      windowsHide: true,
    });
    execFileSync(
      'reg',
      ['add', `HKCU\\Software\\Classes\\${scheme}\\shell\\open\\command`, '/ve', '/d', command, '/f'],
      { windowsHide: true }
    );
    store.data.deeplink.registeredCommand = command;
    store.data.deeplink.registeredAt = util.nowSec();
    store.saveNow();
    log.info(`已注册 ${scheme}:// 协议处理器`);
    return { ok: true, command, changed: true };
  } catch (err) {
    log.error('注册协议处理器失败：' + err.message);
    return { ok: false, command: current, error: err.message };
  }
}

function createLoginFlow(options = {}) {
  const nonce = crypto.randomUUID();
  const id = 'flow_' + util.uid(6);
  const state = (options.cloud ? 'desktop:irisgo:' : 'web:') + nonce;
  const codeVerifier = options.cloud ? crypto.randomBytes(32).toString('base64url') : '';
  const url = new URL(options.cloud ? 'https://api.irisgo.ai/auth/google/desktop' : 'https://api.irisgo.ai/auth/google');
  url.searchParams.set('state', state);
  if (codeVerifier) {
    url.searchParams.set('code_challenge', crypto.createHash('sha256').update(codeVerifier).digest('base64url'));
    url.searchParams.set('code_challenge_method', 'S256');
    url.searchParams.set('analytics_consent', 'false');
  }
  loginFlows.set(id, {
    id,
    nonce,
    state,
    codeVerifier,
    status: 'pending',
    createdAt: Date.now(),
    accountId: null,
    error: '',
    email: '',
    ...options,
  });
  return { id, nonce, url: url.href };
}

async function handleDeepLink(rawUrl, ownerSid = '') {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return { ok: false, error: '无效的登录链接' };
  }
  const code = parsed.searchParams.get('code');
  const state = parsed.searchParams.get('state') || '';
  if (!code) return { ok: false, error: '登录链接里没有授权码' };

  const flow = Array.from(loginFlows.values()).find((f) => f.state && f.state === state);
  if (!flow) return { ok: false, error: '没有匹配的登录流程（可能已过期，请重新发起）' };
  if (flow.cloud && flow.ownerSid !== ownerSid) return { ok: false, error: '请在发起授权的管理会话中完成导入' };
  if (Date.now() - flow.createdAt >= IRISGO_LOGIN_TTL) return { ok: false, error: '授权流程已过期，请重新开始' };
  if (flow.status === 'ok') return { ok: true, duplicate: true, accountId: flow.accountId };
  if (flow.status !== 'pending') return { ok: false, error: '授权正在处理或已失效，请勿重复提交' };

  flow.status = 'exchanging';
  try {
    const session = await irisgo.exchangeGoogleCode(code, proxySlots.resolve(flow.proxyBinding || {}), flow.codeVerifier);
    const profile = session.user || {};
    const email = profile.email || session.info.email || '';
    const userId = profile.id || profile.user_id || session.info.userId || '';
    if (!userId) throw new Error('兑换结果里没有用户 ID');

    let account = store.findAccountByUser(userId);
    if (account) {
      Object.assign(account, {
        token: session.token,
        refreshToken: session.refreshToken || account.refreshToken,
        email: email || account.email,
        exp: session.info.exp || account.exp,
        needsRelogin: false,
        status: 'ok',
        lastError: '',
        cooldownUntil: 0,
        updatedAt: util.nowSec(),
      });
    } else {
      account = store.addAccount({
        label: email || userId,
        email,
        userId,
        token: session.token,
        refreshToken: session.refreshToken,
        exp: session.info.exp || 0,
        source: 'web',
        ...(flow.proxyBinding || {}),
      });
    }
    store.saveNow();
    flow.status = 'ok';
    flow.accountId = account.id;
    flow.email = email;
    log.info(`网页登录成功：${email || userId}`);
    return { ok: true, accountId: account.id, email };
  } catch (err) {
    flow.status = 'error';
    flow.error = flow.cloud ? '授权兑换失败，请重新开始；授权码可能已使用、已过期，或所选代理不可用' : err.message;
    log.warn('网页登录失败：' + flow.error);
    return { ok: false, error: flow.error };
  } finally {
    delete flow.codeVerifier;
  }
}

function processDeepLinkQueue() {
  if (!fs.existsSync(QUEUE_PATH)) return;
  let lines = [];
  try {
    lines = fs.readFileSync(QUEUE_PATH, 'utf8').split('\n').filter(Boolean);
    fs.unlinkSync(QUEUE_PATH);
  } catch {
    return;
  }
  for (const line of lines) {
    try {
      const item = JSON.parse(line);
      if (item.url) handleDeepLink(item.url).catch(() => {});
    } catch {}
  }
}

function cookieOptions(maxAge) {
  return `Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${publicBaseUrl().startsWith('https://') ? '; Secure' : ''}`;
}

function getSession(req) {
  const cookies = util.parseCookies(req);
  const sid = cookies.igp_sess;
  if (!sid) return null;
  const session = sessions.get(sid);
  if (!session) return null;
  if (session.exp < Date.now()) {
    sessions.delete(sid);
    return null;
  }
  return { sid, ...session };
}

function createSession(data) {
  const sid = util.uid(24);
  sessions.set(sid, { ...data, exp: Date.now() + SESSION_TTL_MS, createdAt: Date.now() });
  return sid;
}

function requireSession(req, res, { admin = false } = {}) {
  const session = getSession(req);
  if (!session) {
    util.sendError(res, 401, '未登录', 'authentication_error', 'unauthorized');
    return null;
  }
  if (admin && session.role !== 'admin') {
    util.sendError(res, 403, '需要管理员权限', 'permission_error', 'forbidden');
    return null;
  }
  return session;
}

function requireCsrf(req, res) {
  const header = req.headers['x-igp-request'];
  if (header !== '1') {
    util.sendError(res, 403, '缺少请求头 X-IGP-Request', 'permission_error', 'csrf');
    return false;
  }
  const origin = req.headers.origin;
  if (origin) {
    const allowed = new Set([publicBaseUrl(), `http://127.0.0.1:${store.data.server.port}`, `http://localhost:${store.data.server.port}`]);
    if (!allowed.has(origin)) {
      util.sendError(res, 403, '来源不被允许', 'permission_error', 'bad_origin');
      return false;
    }
  }
  return true;
}

function authenticateApiKey(req) {
  const auth = String(req.headers.authorization || '');
  const match = auth.match(/^Bearer\s+(.+)$/i);
  const raw = match ? match[1].trim() : String(req.headers['x-api-key'] || '').trim();
  if (!raw) return null;
  if (util.safeEqual(raw, store.data.admin.token)) {
    return { id: 'admin', name: 'admin', role: 'admin', accountId: null, rpm: 0 };
  }
  const key = store.findKeyByHash(util.sha256(raw));
  if (!key || !key.enabled) return null;
  return key;
}

function checkRateLimit(key) {
  if (!key.rpm || key.rpm <= 0) return true;
  const now = Date.now();
  const bucket = (rateBuckets.get(key.id) || []).filter((t) => now - t < 60_000);
  if (bucket.length >= key.rpm) {
    rateBuckets.set(key.id, bucket);
    return false;
  }
  bucket.push(now);
  rateBuckets.set(key.id, bucket);
  return true;
}

function drain(res) {
  return new Promise((resolve) => {
    res.resume();
    res.on('end', resolve);
    res.on('error', resolve);
    res.on('close', resolve);
  });
}

function openAiError(res, status, message, type = 'api_error', code = null) {
  util.sendError(res, status, message, type, code);
}

async function handleInference(req, res, kind) {
  const key = authenticateApiKey(req);
  if (!key) {
    openAiError(res, 401, '无效的 API Key。请在面板中创建 Key，并使用 Authorization: Bearer <key>。', 'invalid_request_error', 'invalid_api_key');
    return;
  }
  if (!checkRateLimit(key)) {
    openAiError(res, 429, '该 Key 请求过于频繁，请稍后再试。', 'rate_limit_error', 'rate_limited');
    return;
  }

  let body;
  try {
    body = await util.readJson(req);
  } catch (err) {
    openAiError(res, err.statusCode || 400, err.message);
    return;
  }
  if (kind === 'completions' && !body.messages && typeof body.prompt === 'string') {
    body.messages = [{ role: 'user', content: body.prompt }];
  }
  if (!Array.isArray(body.messages) && kind !== 'responses' && !body.input) {
    openAiError(res, 400, '请求体缺少 messages 字段', 'invalid_request_error', 'invalid_body');
    return;
  }

  const stream = !!body.stream;
  const target = kind === 'responses' ? upstream.PATHS.responses : upstream.PATHS.chat;
  const routing = store.data.routing;
  const maxAttempts = 1 + Math.max(0, Number(routing.maxRetries) || 0);
  const timeoutMs = Number(routing.requestTimeoutMs) || 300000;
  const exclude = new Set();
  let lastFailure = null;

  if (!pool.available().length) {
    openAiError(res, 503, '账号池里没有可用账号。请先在面板中添加 IrisGo 账号，或等待冷却结束。', 'api_error', 'no_account');
    return;
  }

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const account = pool.pick({ exclude, accountId: key.accountId || null });
    if (!account) break;
    exclude.add(account.id);
    const startedAt = Date.now();

    let upstreamRes;
    try {
      upstreamRes = await upstream.request({ ...account, proxy: proxySlots.resolve(account) }, { path: target, body, stream, timeoutMs });
    } catch (err) {
      pool.markNetworkError(account, err.message);
      lastFailure = { status: 502, message: '上游连接失败：' + err.message };
      continue;
    }

    const status = upstreamRes.statusCode;
    if (status === 401 || status === 403) {
      await drain(upstreamRes);
      pool.markAuthFail(account, status);
      lastFailure = { status: 502, message: '账号认证失败，已标记为需要重新登录' };
      continue;
    }
    if (status === 429) {
      const retryAfter = Number(upstreamRes.headers['retry-after']) || Number(routing.cooldownSeconds) || 60;
      await drain(upstreamRes);
      pool.markCooldown(account, retryAfter, '上游返回 429');
      lastFailure = { status: 429, message: '上游限流，请稍后重试' };
      continue;
    }
    if (status >= 500) {
      await drain(upstreamRes);
      pool.markCooldown(account, 20, '上游返回 ' + status);
      lastFailure = { status: 502, message: '上游错误 ' + status };
      continue;
    }

    pool.markLatency(account, Date.now() - startedAt);
    const headers = upstream.filterHeaders(upstreamRes.headers);

    if (status >= 400) {
      const buf = await upstream.collect(upstreamRes, 8 * 1024 * 1024).catch(() => Buffer.alloc(0));
      pool.markUsed(account);
      res.writeHead(status, {
        'Content-Type': upstreamRes.headers['content-type'] || 'application/json; charset=utf-8',
        'Content-Length': buf.length,
        'Cache-Control': 'no-store',
        ...headers,
      });
      res.end(buf);
      return;
    }

    pool.markSuccess(account);
    key.stats = key.stats || { requests: 0 };
    key.stats.requests = (key.stats.requests || 0) + 1;
    key.lastUsedAt = util.nowSec();
    store.save();

    if (stream) {
      res.writeHead(status, {
        'Content-Type': upstreamRes.headers['content-type'] || 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
        ...headers,
      });
      upstreamRes.pipe(res);
      upstreamRes.on('error', () => {
        try {
          res.destroy();
        } catch {}
      });
      res.on('close', () => {
        try {
          upstreamRes.destroy();
        } catch {}
      });
      return;
    }

    const buf = await upstream.collect(upstreamRes).catch((err) => {
      lastFailure = { status: 502, message: '读取上游响应失败：' + err.message };
      return null;
    });
    if (!buf) break;
    let parsed = null;
    try {
      parsed = JSON.parse(buf.toString('utf8'));
    } catch {}
    const usage = upstream.parseUsage(parsed);
    if (usage) pool.markTokens(account, usage);
    res.writeHead(status, {
      'Content-Type': upstreamRes.headers['content-type'] || 'application/json; charset=utf-8',
      'Content-Length': buf.length,
      'Cache-Control': 'no-store',
      ...headers,
    });
    res.end(buf);
    return;
  }

  openAiError(
    res,
    lastFailure?.status || 503,
    lastFailure?.message || '所有账号都不可用，请检查账号池状态。',
    'api_error',
    'upstream_unavailable'
  );
}

async function listModels() {
  const catalog = await models.fetchCatalog({ dataDir: DATA_DIR });
  const visible = models.visibleModels(catalog, store.data.models);
  return models.toOpenAiShape(visible);
}

function serveStatic(req, res, pathname) {
  let rel = pathname === '/' ? '/index.html' : pathname;
  rel = decodeURIComponent(rel.split('?')[0]);
  if (rel.startsWith('/assets/')) rel = rel.slice('/assets'.length);
  const file = path.normalize(path.join(PUBLIC_DIR, rel));
  if (!file.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('forbidden');
    return;
  }
  fs.stat(file, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('not found');
      return;
    }
    const ext = path.extname(file).toLowerCase();
    const types = {
      '.html': 'text/html; charset=utf-8',
      '.js': 'application/javascript; charset=utf-8',
      '.css': 'text/css; charset=utf-8',
      '.svg': 'image/svg+xml',
      '.png': 'image/png',
      '.ico': 'image/x-icon',
      '.json': 'application/json; charset=utf-8',
    };
    res.writeHead(200, {
      'Content-Type': types[ext] || 'application/octet-stream',
      'Cache-Control': ext === '.html' ? 'no-store' : 'public, max-age=300',
      ...(pathname === '/irisgo-authorize.html' ? {
        'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
      } : {}),
    });
    fs.createReadStream(file).pipe(res);
  });
}

function accountPayload(account) {
  const view = irisgo.accountView(account);
  view.proxySlotId = account.proxySlotId || '';
  view.proxySlotName = proxySlots.list().find((s) => s.id === view.proxySlotId)?.name || '';
  view.tokenPreview = util.maskToken(account.token);
  view.expText = irisgo.tokenExpiryText(account.exp);
  view.expiringSoon = irisgo.isExpiringSoon(account.exp);
  return view;
}

function keyPayload(key) {
  return {
    id: key.id,
    name: key.name,
    prefix: key.prefix,
    enabled: key.enabled,
    accountId: key.accountId || null,
    rpm: key.rpm || 0,
    owner: key.owner || null,
    createdAt: key.createdAt,
    lastUsedAt: key.lastUsedAt,
    stats: key.stats || { requests: 0 },
  };
}

function createApiKey({ name, accountId = null, rpm = 0, owner = null }) {
  const secret = 'sk-ig-' + require('node:crypto').randomBytes(24).toString('hex');
  const key = store.addKey({
    name: name || '未命名',
    hash: util.sha256(secret),
    prefix: secret.slice(0, 12) + '…' + secret.slice(-4),
    accountId,
    rpm: Number(rpm) || 0,
    owner,
  });
  return { key, secret };
}

const routes = [];
function route(method, pattern, handler) {
  const names = [];
  const regex = new RegExp(
    '^' +
      pattern.replace(/:[A-Za-z0-9_]+/g, (m) => {
        names.push(m.slice(1));
        return '([^/]+)';
      }) +
      '$'
  );
  routes.push({ method, regex, names, handler });
}

/* ---------------------------------- auth ---------------------------------- */

route('POST', '/api/login', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const body = await util.readJson(req);
  const token = String(body.token || '').trim();
  if (!token || !util.safeEqual(token, store.data.admin.token)) {
    util.sendError(res, 401, '管理员令牌不正确', 'authentication_error', 'invalid_token');
    return;
  }
  const sid = createSession({ role: 'admin', email: 'admin', name: '管理员' });
  res.setHeader('Set-Cookie', `igp_sess=${sid}; ${cookieOptions(604800)}`);
  util.json(res, 200, { ok: true, role: 'admin' });
});

route('POST', '/api/logout', async (req, res) => {
  const session = getSession(req);
  if (session) sessions.delete(session.sid);
  res.setHeader('Set-Cookie', `igp_sess=; ${cookieOptions(0)}`);
  util.json(res, 200, { ok: true });
});

route('GET', '/api/me', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  util.json(res, 200, {
    role: session.role,
    email: session.email,
    name: session.name,
    picture: session.picture || '',
    googleEnabled: !!(store.data.google.enabled && store.data.google.clientId && store.data.google.clientSecret),
    version: VERSION,
  });
});

route('GET', '/api/public-config', async (req, res) => {
  util.json(res, 200, {
    googleEnabled: !!(store.data.google.enabled && store.data.google.clientId && store.data.google.clientSecret),
    version: VERSION,
  });
});

/* -------------------------------- overview -------------------------------- */

route('GET', '/api/overview', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const summary = pool.summary();
  const recentErrors = store.data.accounts
    .filter((a) => a.lastError)
    .slice(0, 10)
    .map((a) => ({
      id: a.id,
      email: a.email,
      label: a.label,
      enabled: a.enabled,
      needsRelogin: a.needsRelogin,
      status: a.status,
      lastError: a.lastError,
      cooldownUntil: a.cooldownUntil,
    }));
  util.json(res, 200, {
    summary,
    routing: store.data.routing,
    server: { host: store.data.server.host, port: store.data.server.port, baseUrl: publicBaseUrl() },
    keys: store.data.keys.length,
    users: store.data.users.length,
    recentErrors,
  });
});

/* -------------------------------- accounts -------------------------------- */

route('GET', '/api/accounts', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  util.json(res, 200, {
    accounts: store.data.accounts.map(accountPayload),
    proxySlots: proxySlots.list(),
    localImportSupported: process.platform === 'win32',
    summary: pool.summary(),
    local: { dir: irisgo.localProfilesDir(), activeUserId: irisgo.activeUserId() },
  });
});

route('GET', '/api/accounts/local-preview', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const scan = irisgo.scanLocalAccounts();
  const known = new Set(store.data.accounts.map((a) => a.userId).filter(Boolean));
  util.json(res, 200, {
    dir: scan.dir,
    exists: scan.exists,
    activeUserId: scan.activeUserId,
    accounts: scan.accounts.map((a) => ({
      userId: a.userId,
      email: a.email,
      exp: a.exp,
      expText: irisgo.tokenExpiryText(a.exp),
      isActive: a.isActive,
      known: known.has(a.userId),
      valid: a.valid,
    })),
    errors: scan.errors,
  });
});

route('POST', '/api/accounts/import-local', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const scan = irisgo.scanLocalAccounts();
  const imported = [];
  const updated = [];
  for (const item of scan.accounts) {
    const existing = store.findAccountByUser(item.userId);
    if (existing) {
      existing.token = item.token;
      existing.refreshToken = item.refreshToken || existing.refreshToken;
      existing.email = item.email || existing.email;
      existing.exp = item.exp || existing.exp;
      existing.needsRelogin = false;
      existing.status = 'ok';
      existing.lastError = '';
      existing.cooldownUntil = 0;
      existing.updatedAt = util.nowSec();
      updated.push(accountPayload(existing));
    } else {
      const created = store.addAccount({
        label: item.email || item.userId,
        email: item.email,
        userId: item.userId,
        token: item.token,
        refreshToken: item.refreshToken,
        exp: item.exp,
        source: 'local',
      });
      imported.push(accountPayload(created));
    }
  }
  store.saveNow();
  log.info(`本机导入：新增 ${imported.length}，更新 ${updated.length}`);
  util.json(res, 200, {
    ok: true,
    imported: imported.length,
    updated: updated.length,
    accounts: imported.concat(updated),
    errors: scan.errors,
  });
});

route('POST', '/api/accounts', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req);
  const token = String(body.token || '').trim();
  if (!token) {
    util.sendError(res, 400, '缺少 token');
    return;
  }
  const info = irisgo.describeToken(token);
  if (!info.valid) {
    util.sendError(res, 400, '这不是一个有效的 JWT，请从 IrisGo 的 app.sqlite 里复制 auth.irisgo 的 token 字段');
    return;
  }
  let binding;
  try {
    binding = proxySlots.binding(body, store.findAccountByUser(info.userId));
  } catch (err) {
    util.sendError(res, 400, err.message);
    return;
  }

  let profile = null;
  try {
    profile = await irisgo.fetchProfile(token, proxySlots.resolve(binding));
  } catch (err) {
    log.warn('添加账号时校验失败：' + err.message);
  }

  const email = profile?.Email || info.email;
  const userId = profile?.ID || info.userId;
  if (!userId) {
    util.sendError(res, 400, '无法从 token 中解析用户 ID');
    return;
  }
  const existing = store.findAccountByUser(userId);
  if (existing) {
    Object.assign(existing, {
      token,
      refreshToken: body.refreshToken || existing.refreshToken,
      email: email || existing.email,
      exp: info.exp || existing.exp,
      ...binding,
      needsRelogin: false,
      status: 'ok',
      lastError: '',
      cooldownUntil: 0,
      updatedAt: util.nowSec(),
    });
    store.saveNow();
    util.json(res, 200, { ok: true, updated: true, account: accountPayload(existing) });
    return;
  }
  const account = store.addAccount({
    label: body.label || email || userId,
    email,
    userId,
    token,
    refreshToken: String(body.refreshToken || ''),
    exp: info.exp || 0,
    ...binding,
    source: 'manual',
  });
  store.saveNow();
  log.info(`新增账号 ${email || userId}`);
  util.json(res, 200, { ok: true, updated: false, account: accountPayload(account) });
});

route('PATCH', '/api/accounts/:id', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const account = store.findAccount(req.params.id);
  if (!account) {
    util.sendError(res, 404, '账号不存在');
    return;
  }
  const body = await util.readJson(req);
  let binding;
  try { binding = proxySlots.binding(body, account); }
  catch (err) { util.sendError(res, err.statusCode || 400, err.message); return; }
  if (body.label !== undefined) account.label = String(body.label).slice(0, 80);
  if (body.enabled !== undefined) account.enabled = !!body.enabled;
  if (body.weight !== undefined) account.weight = Math.max(1, Number(body.weight) || 1);
  if (body.proxy !== undefined || body.proxySlotId !== undefined) {
    Object.assign(account, binding);
    account.status = 'ok';
    account.lastError = '';
    account.cooldownUntil = 0;
  }
  account.updatedAt = util.nowSec();
  store.saveNow();
  util.json(res, 200, { ok: true, account: accountPayload(account) });
});

route('DELETE', '/api/accounts/:id', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const ok = store.removeAccount(req.params.id);
  if (!ok) {
    util.sendError(res, 404, '账号不存在');
    return;
  }
  util.json(res, 200, { ok: true });
});

route('POST', '/api/accounts/:id/test', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const account = store.findAccount(req.params.id);
  if (!account) {
    util.sendError(res, 404, '账号不存在');
    return;
  }
  const started = Date.now();
  try {
    const profile = await irisgo.fetchProfile(account.token, proxySlots.resolve(account));
    const latencyMs = Date.now() - started;
    account.email = profile.Email || account.email;
    account.status = 'ok';
    account.lastError = '';
    account.needsRelogin = false;
    account.cooldownUntil = 0;
    account.stats.lastLatencyMs = latencyMs;
    store.saveNow();
    util.json(res, 200, { ok: true, latencyMs, profile: { email: profile.Email, id: profile.ID } });
  } catch (err) {
    account.status = 'error';
    account.lastError = err.message;
    store.saveNow();
    util.json(res, 200, { ok: false, error: err.message });
  }
});

route('POST', '/api/accounts/:id/refresh', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const account = store.findAccount(req.params.id);
  if (!account) {
    util.sendError(res, 404, '账号不存在');
    return;
  }
  if (!account.refreshToken) {
    util.sendError(res, 400, '该账号没有保存 refresh token，请重新导入');
    return;
  }
  try {
    const result = await irisgo.refreshSession(account.refreshToken, proxySlots.resolve(account));
    account.token = result.token;
    account.refreshToken = result.refreshToken;
    account.exp = result.info.exp || account.exp;
    account.needsRelogin = false;
    account.status = 'ok';
    account.lastError = '';
    account.cooldownUntil = 0;
    store.saveNow();
    util.json(res, 200, { ok: true, account: accountPayload(account) });
  } catch (err) {
    util.json(res, 200, { ok: false, error: err.message });
  }
});

route('POST', '/api/accounts/:id/reset', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  pool.reset(req.params.id);
  util.json(res, 200, { ok: true });
});

route('POST', '/api/accounts/open-app', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const appPath = store.data.settings?.irisgoAppPath || 'F:\\IrisGo\\IrisGo.exe';
  if (!fs.existsSync(appPath)) {
    util.sendError(res, 404, '找不到 IrisGo.exe：' + appPath);
    return;
  }
  try {
    const child = spawn(appPath, [], { detached: true, stdio: 'ignore' });
    child.unref();
    util.json(res, 200, { ok: true });
  } catch (err) {
    util.sendError(res, 500, '启动失败：' + err.message);
  }
});

/* ---------------------------------- keys ---------------------------------- */

route('GET', '/api/keys', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  util.json(res, 200, { keys: store.data.keys.map(keyPayload) });
});

route('POST', '/api/keys', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req);
  if (body.accountId && !store.findAccount(body.accountId)) {
    util.sendError(res, 400, '绑定的账号不存在');
    return;
  }
  const { key, secret } = createApiKey({
    name: body.name,
    accountId: body.accountId || null,
    rpm: body.rpm,
    owner: body.owner || null,
  });
  util.json(res, 200, { ok: true, key: keyPayload(key), secret });
});

route('PATCH', '/api/keys/:id', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const key = store.data.keys.find((k) => k.id === req.params.id);
  if (!key) {
    util.sendError(res, 404, 'Key 不存在');
    return;
  }
  const body = await util.readJson(req);
  if (body.name !== undefined) key.name = String(body.name).slice(0, 60);
  if (body.enabled !== undefined) key.enabled = !!body.enabled;
  if (body.rpm !== undefined) key.rpm = Math.max(0, Number(body.rpm) || 0);
  if (body.accountId !== undefined) {
    if (body.accountId && !store.findAccount(body.accountId)) {
      util.sendError(res, 400, '绑定的账号不存在');
      return;
    }
    key.accountId = body.accountId || null;
  }
  store.saveNow();
  util.json(res, 200, { ok: true, key: keyPayload(key) });
});

route('DELETE', '/api/keys/:id', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const ok = store.removeKey(req.params.id);
  if (!ok) {
    util.sendError(res, 404, 'Key 不存在');
    return;
  }
  util.json(res, 200, { ok: true });
});

/* ------------------------------ user's keys ------------------------------- */

route('GET', '/api/my/keys', async (req, res) => {
  const session = requireSession(req, res);
  if (!session) return;
  const keys = store.data.keys.filter((k) => k.owner === session.email);
  util.json(res, 200, { keys: keys.map(keyPayload) });
});

route('POST', '/api/my/keys', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res);
  if (!session) return;
  const owned = store.data.keys.filter((k) => k.owner === session.email);
  if (owned.length >= 3) {
    util.sendError(res, 400, '最多只能创建 3 个 Key，请先删除旧的');
    return;
  }
  const body = await util.readJson(req);
  const { key, secret } = createApiKey({ name: body.name || session.email, owner: session.email, rpm: Number(body.rpm) || 0 });
  util.json(res, 200, { ok: true, key: keyPayload(key), secret });
});

route('DELETE', '/api/my/keys/:id', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res);
  if (!session) return;
  const key = store.data.keys.find((k) => k.id === req.params.id);
  if (!key || key.owner !== session.email) {
    util.sendError(res, 404, 'Key 不存在');
    return;
  }
  store.removeKey(key.id);
  util.json(res, 200, { ok: true });
});

/* -------------------------------- settings -------------------------------- */

route('GET', '/api/settings', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const google = store.data.google;
  util.json(res, 200, {
    server: { ...store.data.server, baseUrl: publicBaseUrl() },
    routing: store.data.routing,
    google: {
      enabled: google.enabled,
      clientId: google.clientId,
      clientSecretSet: !!google.clientSecret,
      allowedEmails: google.allowedEmails,
      allowedDomains: google.allowedDomains,
      autoProvision: google.autoProvision,
      proxy: google.proxy || '',
      redirectUri: publicBaseUrl() + '/auth/google/callback',
    },
    app: { irisgoAppPath: store.data.settings?.irisgoAppPath || 'F:\\IrisGo\\IrisGo.exe' },
    version: VERSION,
  });
});

route('PATCH', '/api/settings', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req);

  if (body.routing) {
    const r = body.routing;
    if (r.strategy && ['round_robin', 'least_used', 'random'].includes(r.strategy)) store.data.routing.strategy = r.strategy;
    if (r.maxRetries !== undefined) store.data.routing.maxRetries = util.clamp(Number(r.maxRetries) || 0, 0, 5);
    if (r.cooldownSeconds !== undefined) store.data.routing.cooldownSeconds = util.clamp(Number(r.cooldownSeconds) || 60, 5, 3600);
    if (r.requestTimeoutMs !== undefined) store.data.routing.requestTimeoutMs = util.clamp(Number(r.requestTimeoutMs) || 300000, 10000, 900000);
  }
  if (body.google) {
    const g = body.google;
    if (g.enabled !== undefined) store.data.google.enabled = !!g.enabled;
    if (g.clientId !== undefined) store.data.google.clientId = String(g.clientId).trim();
    if (g.clientSecret) store.data.google.clientSecret = String(g.clientSecret).trim();
    if (g.allowedEmails !== undefined) {
      store.data.google.allowedEmails = String(g.allowedEmails).split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    }
    if (g.allowedDomains !== undefined) {
      store.data.google.allowedDomains = String(g.allowedDomains).split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    }
    if (g.autoProvision !== undefined) store.data.google.autoProvision = !!g.autoProvision;
    if (g.proxy !== undefined) store.data.google.proxy = String(g.proxy).trim();
  }
  if (body.server) {
    if (body.server.publicBaseUrl !== undefined) store.data.server.publicBaseUrl = String(body.server.publicBaseUrl).trim();
  }
  if (body.app) {
    store.data.settings = store.data.settings || {};
    if (body.app.irisgoAppPath) store.data.settings.irisgoAppPath = String(body.app.irisgoAppPath).trim();
  }
  store.saveNow();
  util.json(res, 200, { ok: true });
});

route('POST', '/api/admin/rotate-token', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const token = 'igp_' + require('node:crypto').randomBytes(24).toString('hex');
  store.data.admin.token = token;
  store.saveNow();
  util.json(res, 200, { ok: true, token });
});

route('GET', '/api/users', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  util.json(res, 200, { users: store.data.users });
});

route('DELETE', '/api/users/:sub', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  store.data.users = store.data.users.filter((u) => u.sub !== req.params.sub);
  store.saveNow();
  util.json(res, 200, { ok: true });
});

/* --------------------------------- google --------------------------------- */

route('GET', '/auth/google/start', async (req, res) => {
  const cfg = store.data.google;
  if (!cfg.enabled || !cfg.clientId || !cfg.clientSecret) {
    res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<h3>Google 登录未配置</h3><p>请先用管理员令牌登录，在「设置」里填写 Client ID / Client Secret。</p>');
    return;
  }
  const state = util.uid(16);
  let next = String(req.query?.next || '/');
  if (!next.startsWith('/') || next.startsWith('//')) next = '/';
  oauthStates.set(state, { createdAt: Date.now(), next });
  const redirectUri = publicBaseUrl() + '/auth/google/callback';
  const url = oauth.buildAuthUrl(cfg, redirectUri, state);
  res.writeHead(302, { Location: url });
  res.end();
});

route('GET', '/auth/google/callback', async (req, res) => {
  const { code, state, error } = req.query || {};
  const pending = state ? oauthStates.get(state) : null;
  if (pending) oauthStates.delete(state);
  if (error) {
    res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<h3>Google 返回错误</h3><p>${String(error).replace(/[<>]/g, '')}</p>`);
    return;
  }
  if (!code || !pending) {
    res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<h3>登录状态已失效</h3><p>请回到面板重新点击登录。</p>');
    return;
  }
  try {
    const cfg = store.data.google;
    const redirectUri = publicBaseUrl() + '/auth/google/callback';
    const tokens = await oauth.exchangeCode(cfg, code, redirectUri);
    const profile = await oauth.verifyIdToken(tokens.id_token, cfg.clientId, cfg.proxy || '');
    if (!oauth.isAllowed(cfg, profile.email)) {
      res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`<h3>没有访问权限</h3><p>${String(profile.email).replace(/[<>]/g, '')} 不在允许名单内。</p>`);
      return;
    }
    if (!cfg.autoProvision) {
      const known = store.data.users.some((u) => u.sub === profile.sub);
      if (!known) {
        res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end('<h3>账号未开通</h3><p>请联系管理员开通。</p>');
        return;
      }
    }
    store.upsertUser({ sub: profile.sub, email: profile.email, name: profile.name, picture: profile.picture });
    const sid = createSession({
      role: 'user',
      email: profile.email,
      name: profile.name || profile.email,
      sub: profile.sub,
      picture: profile.picture || '',
    });
    res.writeHead(302, {
      Location: pending.next || '/',
      'Set-Cookie': `igp_sess=${sid}; ${cookieOptions(604800)}`,
    });
    res.end();
  } catch (err) {
    log.error('Google 登录失败：' + err.message);
    res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<h3>登录失败</h3><p>' + String(err.message).replace(/[<>]/g, '') + '</p>');
  }
});

/* ------------------------------- web sign-in ------------------------------- */

route('POST', '/api/oauth/web/start', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req, 16384);
  const cloud = body.mode === 'cloud' || process.platform !== 'win32';
  if (cloud) {
    const active = Array.from(loginFlows.values()).filter((f) => Date.now() - f.createdAt < IRISGO_LOGIN_TTL);
    if (active.length >= 500 || active.filter((f) => f.ownerSid === session.sid && f.status === 'pending').length >= 5) {
      return util.sendError(res, 429, '待完成的授权过多，请完成已有流程或稍后再试');
    }
    const binding = proxySlots.binding(body);
    const flow = createLoginFlow({ cloud: true, ownerSid: session.sid, proxyBinding: binding });
    return util.json(res, 200, { ok: true, mode: 'copy_callback', flowId: flow.id, url: flow.url, expiresAt: Date.now() + IRISGO_LOGIN_TTL });
  }
  const scheme = ensureScheme();
  const flow = createLoginFlow({ ownerSid: session.sid });
  util.json(res, 200, { ok: true, flowId: flow.id, url: flow.url, scheme });
});

route('POST', '/api/oauth/web/complete', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req, 20000);
  const flow = loginFlows.get(String(body.flowId || ''));
  let callback;
  try { callback = callbackForFlow(body.callbackUrl, flow, session.sid); }
  catch (err) { return util.sendError(res, err.statusCode || 400, err.message); }
  const result = await handleDeepLink(callback, session.sid);
  util.json(res, result.ok ? 200 : 400, result);
});

route('GET', '/api/oauth/web/flow/:id', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const flow = loginFlows.get(req.params.id);
  if (!flow || (flow.ownerSid && flow.ownerSid !== session.sid)) {
    util.sendError(res, 404, '登录流程不存在');
    return;
  }
  if (flow.status === 'pending' && Date.now() - flow.createdAt > 10 * 60 * 1000) {
    flow.status = 'expired';
    flow.error = '登录超时，请重新发起';
    delete flow.codeVerifier;
  }
  util.json(res, 200, {
    id: flow.id,
    status: flow.status,
    accountId: flow.accountId,
    email: flow.email,
    error: flow.error,
  });
});

route('POST', '/api/oauth/deeplink', async (req, res) => {
  const body = await util.readJson(req);
  const secret = String(body.secret || req.headers['x-igp-secret'] || '');
  if (!util.safeEqual(secret, store.data.deeplink.secret)) {
    util.sendError(res, 403, '无效的 deeplink 密钥', 'permission_error', 'bad_secret');
    return;
  }
  const result = await handleDeepLink(String(body.url || ''));
  util.json(res, result.ok ? 200 : 400, result);
});

/* ---------------------------------- models --------------------------------- */

route('GET', '/api/models', async (req, res) => {
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const catalog = await models.fetchCatalog({ dataDir: DATA_DIR });
  const visible = models.visibleModels(catalog, store.data.models);
  const visibleIds = new Set(visible.map((m) => m.id));
  util.json(res, 200, {
    source: catalog.source,
    fetchedAt: catalog.fetchedAt,
    error: catalog.error || '',
    total: catalog.models.length,
    visibleCount: visible.length,
    config: {
      includeAuto: store.data.models.includeAuto !== false,
      hidden: store.data.models.hidden || [],
      only: store.data.models.only || [],
    },
    models: catalog.models.map((m) => ({ ...m, visible: visibleIds.has(m.id) })),
  });
});

route('PATCH', '/api/models', async (req, res) => {
  if (!requireCsrf(req, res)) return;
  const session = requireSession(req, res, { admin: true });
  if (!session) return;
  const body = await util.readJson(req);
  if (body.hidden !== undefined) store.data.models.hidden = Array.isArray(body.hidden) ? body.hidden.map(String) : [];
  if (body.only !== undefined) store.data.models.only = Array.isArray(body.only) ? body.only.map(String) : [];
  if (body.includeAuto !== undefined) store.data.models.includeAuto = !!body.includeAuto;
  store.saveNow();
  if (body.refresh) {
    models.clearMemoryCache();
    const catalog = await models.fetchCatalog({ dataDir: DATA_DIR, force: true });
    util.json(res, 200, {
      ok: true,
      source: catalog.source,
      total: catalog.models.length,
      error: catalog.error || '',
    });
    return;
  }
  util.json(res, 200, { ok: true });
});

/* ---------------------------------- openai -------------------------------- */

route('GET', '/v1/models', async (req, res) => {
  const key = authenticateApiKey(req);
  if (!key) {
    openAiError(res, 401, '无效的 API Key', 'invalid_request_error', 'invalid_api_key');
    return;
  }
  util.json(res, 200, await listModels());
});

route('POST', '/v1/chat/completions', async (req, res) => {
  await handleInference(req, res, 'chat');
});

route('POST', '/v1/completions', async (req, res) => {
  await handleInference(req, res, 'completions');
});

route('POST', '/v1/responses', async (req, res) => {
  await handleInference(req, res, 'responses');
});

route('GET', '/health', async (req, res) => {
  util.json(res, 200, { ok: true, version: VERSION, accounts: pool.summary() });
});

/* --------------------------------- server --------------------------------- */

function matchRoute(method, pathname) {
  for (const r of routes) {
    if (r.method !== method) continue;
    const m = r.regex.exec(pathname);
    if (!m) continue;
    const params = {};
    r.names.forEach((name, i) => {
      params[name] = decodeURIComponent(m[i + 1]);
    });
    return { handler: r.handler, params };
  }
  return null;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, publicBaseUrl());
  const pathname = url.pathname;
  req.query = Object.fromEntries(url.searchParams.entries());

  if (req.method === 'OPTIONS' && pathname.startsWith('/v1/')) {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-API-Key',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Max-Age': '86400',
    });
    res.end();
    return;
  }
  if (pathname.startsWith('/v1/')) {
    res.setHeader('Access-Control-Allow-Origin', '*');
  }

  const matched = matchRoute(req.method, pathname);
  if (matched) {
    req.params = matched.params;
    try {
      await matched.handler(req, res);
    } catch (err) {
      log.error(`${req.method} ${pathname} 失败：${err.stack || err.message}`);
      if (!res.headersSent) util.sendError(res, err.statusCode || 500, err.message || '服务器内部错误');
      else res.destroy();
    }
    return;
  }

  if (req.method === 'GET') {
    serveStatic(req, res, pathname);
    return;
  }
  util.sendError(res, 404, 'not found', 'invalid_request_error', 'not_found');
});

setInterval(() => {
  const now = Date.now();
  for (const [sid, session] of sessions) {
    if (session.exp < now) sessions.delete(sid);
  }
  for (const [state, info] of oauthStates) {
    if (now - info.createdAt > STATE_TTL_MS) oauthStates.delete(state);
  }
  for (const [id, bucket] of rateBuckets) {
    const fresh = bucket.filter((t) => now - t < 60_000);
    if (fresh.length) rateBuckets.set(id, fresh);
    else rateBuckets.delete(id);
  }
  for (const [id, flow] of loginFlows) {
    if (now - flow.createdAt >= IRISGO_LOGIN_TTL) delete flow.codeVerifier;
    if (now - flow.createdAt > 30 * 60 * 1000) loginFlows.delete(id);
  }
}, 60_000).unref();

function start() {
  const host = store.data.server.host || '127.0.0.1';
  const port = Number(store.data.server.port) || 8787;

  if (boot.created) {
    fs.writeFileSync(path.join(DATA_DIR, 'admin-token.txt'), store.data.admin.token + '\n', 'utf8');
  }

  server.listen(port, host, () => {
    const base = publicBaseUrl();
    console.log('');
    console.log('  IrisGo Proxy 已启动');
    console.log('  ------------------------------------------------');
    console.log('  面板地址 : ' + base);
    console.log('  接口地址 : ' + base + '/v1');
    console.log('  管理员令牌: 请在受保护的 data/config.json 中查看（不会输出到日志）');
    console.log('  ------------------------------------------------');
    console.log('  账号池: ' + store.data.accounts.length + ' 个账号, ' + store.data.keys.length + ' 个 Key');
    console.log('');
    log.info(`服务启动 http://${host}:${port}`);
    processDeepLinkQueue();
  });

  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`\n端口 ${port} 已被占用。请修改 data/config.json 里的 server.port 后重试。\n`);
    } else {
      console.error('服务启动失败：', err);
    }
    process.exit(1);
  });
}

process.on('SIGINT', () => {
  console.log('\n正在退出，保存配置…');
  store.saveNow();
  process.exit(0);
});
process.on('SIGTERM', () => {
  store.saveNow();
  process.exit(0);
});

start();
