'use strict';
// Isolated fixtures only. Never opens the owner's data or contacts IrisGo.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const { fork } = require('node:child_process');
const { Readable } = require('node:stream');
const root = path.resolve(__dirname, '..');
const { ProxySlots } = require('../lib/proxy-slots');
const { TTL_MS, callbackForFlow } = require('../lib/irisgo-login');
const token = (id) => 'e30.' + Buffer.from(JSON.stringify({ sub: id, exp: 4000000000 })).toString('base64url') + '.test';

if (process.env.IGP_TEST_CHILD === '1') {
  const irisgo = require('../lib/irisgo');
  const upstream = require('../lib/upstream');
  irisgo.fetchProfile = async (jwt, proxy) => {
    process.send({ kind: 'profile', proxy });
    return { ID: irisgo.describeToken(jwt).userId };
  };
  irisgo.refreshSession = async (refresh, proxy) => {
    process.send({ kind: 'refresh', proxy });
    return { token: token(refresh), refreshToken: refresh, info: { exp: 4000000000 } };
  };
  irisgo.exchangeGoogleCode = async (code, proxy, verifier) => {
    assert.match(verifier, /^[A-Za-z0-9_-]{43}$/);
    process.send({ kind: 'exchange', proxy, challenge: crypto.createHash('sha256').update(verifier).digest('base64url') });
    if (code === 'bad-secret') throw new Error('PRIVATE_UPSTREAM_SECRET');
    if (code === 'slow-google') await new Promise((r) => setTimeout(r, 50));
    const userId = code === 'existing-google' ? 'user0' : 'google-new';
    return { token: token(userId), refreshToken: userId, info: { userId, exp: 4000000000 }, user: { id: userId } };
  };
  upstream.request = async (account, opts) => {
    process.send({ kind: 'chat', proxy: account.proxy });
    const stream = opts.stream;
    const res = Readable.from([Buffer.from(stream ? 'data: {"choices":[]}\n\ndata: [DONE]\n\n' : '{"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}')]);
    res.statusCode = 200;
    res.headers = { 'content-type': stream ? 'text/event-stream' : 'application/json' };
    return res;
  };
}

async function main() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'igp-routing-test-'));
  let child;
  const seen = [];
  const slotFile = path.join(dir, 'proxy-slots.private.json');
  const slots = [1, 2].map((n) => ({ id: 'slot' + n, name: 'Test ' + n, url: 'http://fixture:private@127.0.0.1:' + (18000 + n) }));
  const writeSlots = () => fs.writeFileSync(slotFile, JSON.stringify(slots));
  const stop = async () => {
    if (child && child.exitCode === null) await new Promise((resolve) => { child.once('exit', resolve); child.kill(); });
  };
  try {
    writeSlots();
    const catalog = new ProxySlots(slotFile);
    assert(!JSON.stringify(catalog.list()).includes('private'));
    assert.equal(catalog.resolve({ proxySlotId: 'slot1' }), slots[0].url);
    assert.throws(() => catalog.resolve({ proxySlotId: 'gone', proxy: slots[0].url }));
    const listener = net.createServer();
    await new Promise((resolve) => listener.listen(0, '127.0.0.1', resolve));
    const port = listener.address().port;
    await new Promise((resolve) => listener.close(resolve));
    const { Store } = require('../lib/store');
    const store = new Store(path.join(dir, 'config.json'));
    store.load();
    store.data.server.port = port;
    store.data.routing.maxRetries = 0;
    if (process.env.IGP_BROWSER_TEST === '1') store.data.admin.token = 'fixture-admin-not-a-real-secret';
    store.saveNow();
    const base = 'http://127.0.0.1:' + port;
    let cookie = '';
    async function req(url, body, method = 'POST', auth = true) {
      const res = await fetch(base + url, { method, headers: { 'Content-Type': 'application/json',
        'X-IGP-Request': '1', ...(auth ? { Cookie: cookie, Authorization: 'Bearer ' + store.data.admin.token } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) }).catch((err) => { throw new Error(method + ' ' + url + ': ' + err.message, { cause: err }); });
      const text = await res.text();
      return { status: res.status, headers: res.headers, text, data: text.startsWith('{') ? JSON.parse(text) : null };
    }
    async function start() {
      child = fork(path.join(root, 'server.js'), [], { silent: true, execArgv: ['--require', __filename],
        env: { ...process.env, IGP_TEST_CHILD: '1', IGP_DATA_DIR: dir } });
      child.stdout.resume(); child.stderr.on('data', (chunk) => process.stderr.write(chunk)); child.on('message', (m) => seen.push(m));
      let ready = false;
      for (let i = 0; i < 100; i++) {
        try { ready = (await req('/health', undefined, 'GET', false)).status === 200; } catch {}
        if (ready) break;
        await new Promise((r) => setTimeout(r, 50));
      }
      assert(ready, 'test server starts');
      const login = await req('/api/login', { token: store.data.admin.token });
      assert.equal(login.status, 200);
      cookie = login.headers.get('set-cookie').split(';')[0];
    }
    await start();
    if (process.env.IGP_BROWSER_TEST === '1') {
      console.log('BROWSER_QA ' + JSON.stringify({ baseUrl: base, token: store.data.admin.token }));
      await new Promise((resolve) => { process.once('SIGINT', resolve); process.once('SIGTERM', resolve); });
      return;
    }
    assert.equal((await req('/api/accounts', undefined, 'GET', false)).status, 401);
    assert.equal((await req('/api/accounts', { token: token('bad'), proxySlotId: 'gone' })).status, 400);
    const ids = [];
    const secrets = [];
    for (let i = 0; i < 2; i++) {
      const added = await req('/api/accounts', { token: token('user' + i), refreshToken: 'user' + i, proxySlotId: slots[i].id });
      assert.equal(added.status, 200);
      ids.push(added.data.account.id);
      assert.equal(added.data.account.proxy, '');
      assert.deepEqual(seen.at(-1), { kind: 'profile', proxy: slots[i].url });
      const key = await req('/api/keys', { name: 'test', accountId: ids[i] });
      assert.equal(key.status, 200);
      const secret = key.data.secret || key.data.key;
      secrets.push(secret);
      for (const stream of [false, true]) {
        const r = await fetch(base + '/v1/chat/completions', { method: 'POST', headers: { Authorization: 'Bearer ' + secret, 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: [{ role: 'user', content: 'fixture' }], stream }) });
        assert.equal(r.status, 200); await r.text();
        assert.deepEqual(seen.at(-1), { kind: 'chat', proxy: slots[i].url });
      }
      for (const kind of ['test', 'refresh']) {
        const r = await req('/api/accounts/' + ids[i] + '/' + kind, {});
        assert.equal(r.data.ok, true);
        assert.deepEqual(seen.at(-1), { kind: kind === 'test' ? 'profile' : 'refresh', proxy: slots[i].url });
      }
    }
    const accounts = await req('/api/accounts', undefined, 'GET');
    assert(!accounts.text.includes('fixture:private'));
    assert.equal((await req('/api/accounts/' + ids[0], { label: 'MUST NOT SAVE', enabled: false, proxySlotId: 'gone' }, 'PATCH')).status, 400);
    let rows = (await req('/api/accounts', undefined, 'GET')).data.accounts;
    assert.notEqual(rows[0].label, 'MUST NOT SAVE'); assert(rows[0].enabled);
    await stop(); await start();
    rows = (await req('/api/accounts', undefined, 'GET')).data.accounts;
    assert.equal(rows[1].proxySlotId, 'slot2');
    // Cloud Google authorization: official callback, session ownership, nonce and single use.
    const begin = async (slot = 'slot2') => {
      const r = await req('/api/oauth/web/start', { mode: 'cloud', proxySlotId: slot });
      assert.equal(r.status, 200); assert.equal(r.data.mode, 'copy_callback');
      assert(!JSON.stringify(r.data).includes('private'));
      assert(!/codeVerifier|code_verifier/.test(r.text));
      const url = new URL(r.data.url);
      assert.equal(url.pathname, '/auth/google/desktop');
      assert.match(url.searchParams.get('state'), /^desktop:irisgo:/);
      assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
      assert.match(url.searchParams.get('code_challenge'), /^[A-Za-z0-9_-]{43}$/);
      return r.data;
    };
    const callback = (f, code = 'new-google') => 'https://irisgo.ai/oauth/google?' + new URLSearchParams({ code, state: new URL(f.url).searchParams.get('state') });
    assert.equal((await req('/api/oauth/web/start', { mode: 'cloud' }, 'POST', false)).status, 401);
    const f = await begin();
    const finish = (f, url) => req('/api/oauth/web/complete', { flowId: f.flowId, callbackUrl: url });
    assert.equal((await finish(f, callback(f).replace('irisgo.ai/', 'attacker.invalid/'))).status, 400);
    assert.equal((await finish(f, callback(f).replace('desktop%3Airisgo%3A', 'web%3A'))).status, 400);
    const pending = await req('/api/oauth/web/flow/' + f.flowId, undefined, 'GET');
    assert(!/codeVerifier|code_verifier/.test(pending.text));
    const secondLogin = await req('/api/login', { token: store.data.admin.token });
    const cookieB = secondLogin.headers.get('set-cookie').split(';')[0];
    const cross = await fetch(base + '/api/oauth/web/complete', { method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-IGP-Request': '1', Cookie: cookieB },
      body: JSON.stringify({ flowId: f.flowId, callbackUrl: callback(f) }) });
    assert.equal(cross.status, 404); await cross.text();
    const statusB = await fetch(base + '/api/oauth/web/flow/' + f.flowId, { headers: { Cookie: cookieB } });
    assert.equal(statusB.status, 404); await statusB.text();
    const countBefore = seen.length;
    assert.equal((await finish(f, callback(f))).data.ok, true);
    assert.deepEqual(seen.at(-1), { kind: 'exchange', proxy: slots[1].url,
      challenge: new URL(f.url).searchParams.get('code_challenge') });
    assert.equal((await finish(f, callback(f))).data.duplicate, true);
    assert.equal(seen.length, countBefore + 1);
    let cloudRows = (await req('/api/accounts', undefined, 'GET')).data.accounts;
    assert.equal(cloudRows.find((a) => a.userId === 'google-new').proxySlotId, 'slot2');
    const existingFlow = await begin();
    assert.notEqual(new URL(f.url).searchParams.get('state'), new URL(existingFlow.url).searchParams.get('state'));
    assert.notEqual(new URL(f.url).searchParams.get('code_challenge'), new URL(existingFlow.url).searchParams.get('code_challenge'));
    assert.equal((await finish(existingFlow, callback(existingFlow, 'existing-google').replace('https://irisgo.ai/oauth/google', 'ai.irisgo://oauth/callback'))).data.ok, true);
    assert.equal(seen.at(-1).challenge, new URL(existingFlow.url).searchParams.get('code_challenge'));
    cloudRows = (await req('/api/accounts', undefined, 'GET')).data.accounts;
    assert.equal(cloudRows.find((a) => a.userId === 'user0').proxySlotId, 'slot1');
    const badFlow = await begin();
    const failed = await finish(badFlow, callback(badFlow, 'bad-secret'));
    assert.equal(failed.status, 400); assert(!failed.text.includes('PRIVATE_UPSTREAM_SECRET'));
    const slow = await begin();
    const concurrent = await Promise.all([finish(slow, callback(slow, 'slow-google')), finish(slow, callback(slow, 'slow-google'))]);
    assert.deepEqual(concurrent.map((r) => r.status).sort(), [200, 400]);
    const expiredFixture = { cloud: true, ownerSid: 'same', state: 'desktop:irisgo:nonce', createdAt: 1000 };
    const sample = 'https://irisgo.ai/oauth/google?code=fixture&state=desktop:irisgo:nonce';
    assert.equal(callbackForFlow(sample, expiredFixture, 'same', 1001), sample);
    assert.throws(() => callbackForFlow(sample, expiredFixture, 'same', 1000 + TTL_MS), /过期/);
    assert.throws(() => callbackForFlow(sample, expiredFixture, 'other', 1001), /当前登录/);
    for (const value of [sample + '&code=again', sample + '#fragment', sample.replace('https://irisgo.ai', 'https://me@irisgo.ai'), sample.replace('code=fixture', 'error=access_denied')]) {
      assert.throws(() => callbackForFlow(value, expiredFixture, 'same', 1001));
    }
    assert(callbackForFlow('ai.irisgo://oauth/callback?code=fixture&state=desktop:irisgo:nonce', expiredFixture, 'same', 1001));
    assert.throws(() => callbackForFlow(sample.replace('desktop:irisgo:', 'web:'), expiredFixture, 'same', 1001));
    assert.throws(() => callbackForFlow(sample + '&state=desktop:irisgo:nonce', expiredFixture, 'same', 1001));
    const unauthorized = await fetch(base + '/api/oauth/web/start', { method: 'POST', headers: { Cookie: cookie }, body: '{}' });
    assert.equal(unauthorized.status, 403); await unauthorized.text();
    const maliciousOrigin = await fetch(base + '/api/oauth/web/start', { method: 'POST', headers: { Cookie: cookie, 'X-IGP-Request': '1', Origin: 'https://attacker.invalid' }, body: '{}' });
    assert.equal(maliciousOrigin.status, 403); await maliciousOrigin.text();
    const page = await fetch(base + '/irisgo-authorize.html');
    assert.equal(page.headers.get('referrer-policy'), 'no-referrer');
    assert(page.headers.get('content-security-policy').includes("frame-ancestors 'none'")); await page.text();
    console.log('PASS cloud OAuth: ownership, nonce, expiry, origin/CSRF, replay/concurrency, sanitized errors, selected proxy, existing binding preserved');
    slots[1].enabled = false; writeSlots();
    const count = seen.length;
    assert.equal((await req('/api/accounts/' + ids[1] + '/test', {})).data.ok, false);
    assert.equal((await req('/api/accounts/' + ids[1] + '/refresh', {})).data.ok, false);
    const failedChat = await fetch(base + '/v1/chat/completions', { method: 'POST', headers: {
      Authorization: 'Bearer ' + secrets[1], 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: 'fixture' }] }) });
    assert.equal(failedChat.status, 502); await failedChat.text();
    assert.equal(seen.length, count, 'disabled binding makes no upstream request');
    assert.equal((await req('/api/accounts/' + ids[1], { proxy: 'socks5://127.0.0.1:1080', proxySlotId: '' }, 'PATCH')).status, 200);
    assert.equal((await req('/api/accounts/' + ids[1] + '/test', {})).data.ok, true);
    assert.equal(seen.at(-1).proxy, 'socks5://127.0.0.1:1080');
    await req('/api/accounts/' + ids[1], { proxy: '', proxySlotId: '' }, 'PATCH');
    await req('/api/accounts/' + ids[1] + '/test', {});
    assert.equal(seen.at(-1).proxy, '');
    fs.writeFileSync(slotFile, '{broken');
    assert.throws(() => catalog.resolve({ proxySlotId: 'slot1' }), /目录不可用/);
    assert(!fs.readFileSync(path.join(dir, 'proxy.log'), 'utf8').includes('PRIVATE_UPSTREAM_SECRET'));
    assert(!/codeVerifier|code_verifier/.test(fs.readFileSync(path.join(dir, 'config.json'), 'utf8')));
    console.log('PASS isolated API: auth, account separation, chat/SSE/profile/refresh, persistence, atomic PATCH, fail-closed, manual/direct, credential redaction');
  } finally {
    await stop();
    fs.rmSync(dir, { recursive: true, force: true });
  }
  // Real CONNECT sockets to two local rejecting proxies: no external traffic.
  const { agentFor, clearAgentCache } = require('../lib/proxies');
  const https = require('node:https');
  const hits = [];
  for (let i = 0; i < 2; i++) {
    const proxy = net.createServer((socket) => socket.once('data', (data) => {
      assert(data.toString().startsWith('CONNECT api.irisgo.ai:443'));
      hits.push(i); socket.end('HTTP/1.1 502 Test Fixture\r\n\r\n');
    }));
    await new Promise((r) => proxy.listen(0, '127.0.0.1', r));
    await new Promise((r) => {
      const request = https.get('https://api.irisgo.ai/auth/profile', { agent: agentFor('http://127.0.0.1:' + proxy.address().port) });
      request.on('error', r);
    });
    await new Promise((r) => proxy.close(r));
  }
  clearAgentCache(); assert.deepEqual(hits, [0, 1]);
  console.log('PASS actual HTTP CONNECT transport: two independent proxy listeners');
  // Intercept the real exchange helper: no external OAuth request or real credentials.
  const { EventEmitter } = require('node:events');
  const original = https.request;
  const verifier = crypto.randomBytes(32).toString('base64url');
  let sent;
  try {
    https.request = (opts, callback) => {
      const request = new EventEmitter();
      let body = '';
      request.setTimeout = () => {};
      request.write = (chunk) => { body += chunk; };
      request.end = () => {
        sent = { path: opts.path, body: JSON.parse(body) };
        const response = Readable.from([Buffer.from(JSON.stringify({ token: token('pkce-fixture') }))]);
        response.statusCode = 200; response.headers = {};
        process.nextTick(() => callback(response));
      };
      return request;
    };
    const irisgo = require('../lib/irisgo');
    const session = await irisgo.exchangeGoogleCode('fixture-code', '', verifier);
    assert.equal(session.info.userId, 'pkce-fixture');
    assert.deepEqual(sent, { path: '/auth/callback/google', body: { code: 'fixture-code', code_verifier: verifier } });
    await assert.rejects(irisgo.exchangeGoogleCode('fixture-code', '', 'invalid'), /PKCE/);
  } finally { https.request = original; }
  console.log('PASS desktop PKCE: unique S256 challenge, verifier kept server-side, desktop callback, exact state and exchange request body');
}

if (require.main === module) main().catch((err) => { console.error(err); process.exitCode = 1; });
