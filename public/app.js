'use strict';

const state = {
  me: null,
  page: 'overview',
  accounts: [],
  proxySlots: [],
  localImportSupported: true,
  keys: [],
  models: { list: [], config: {} },
  settings: null,
  baseUrl: location.origin,
  refreshTimer: null,
  modalPoll: null,
  loginWatch: null,
  webLoginTimer: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* --------------------------------- helpers -------------------------------- */

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    headers['Content-Type'] = 'application/json';
  }
  if ((opts.method || 'GET').toUpperCase() !== 'GET') headers['X-IGP-Request'] = '1';
  const res = await fetch(path, { credentials: 'same-origin', ...opts, headers });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (res.status === 401) {
    showLogin();
    throw new Error('登录已失效');
  }
  if (!res.ok) throw new Error(data?.error?.message || data?.raw || 'HTTP ' + res.status);
  return data;
}

function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  $('#toast-root').appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity .25s';
    setTimeout(() => el.remove(), 260);
  }, 3200);
}

function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function statusOf(acc) {
  if (!acc.enabled) return { cls: 'off', dot: 'off', text: '已停用' };
  if (acc.needsRelogin) return { cls: 'err', dot: 'err', text: '需重新登录' };
  const left = Math.ceil((acc.cooldownUntil - Date.now()) / 1000);
  if (left > 0) return { cls: 'warn', dot: 'warn', text: `冷却 ${left}s` };
  if (acc.status === 'error') return { cls: 'err', dot: 'err', text: '异常' };
  return { cls: 'ok', dot: 'ok', text: '正常' };
}

/* ---------------------------------- auth ---------------------------------- */

function showLogin() {
  stopRefresh();
  $('#boot').classList.add('hidden');
  $('#app-view').classList.add('hidden');
  $('#login-view').classList.remove('hidden');
  api('/api/public-config')
    .then((cfg) => {
      if (cfg.googleEnabled) {
        $('#google-login').classList.remove('hidden');
        $('#google-hint').classList.add('hidden');
      } else {
        $('#google-login').classList.add('hidden');
        $('#google-hint').classList.remove('hidden');
      }
    })
    .catch(() => {});
}

async function boot() {
  try {
    const res = await fetch('/api/me', { credentials: 'same-origin' });
    if (!res.ok) return showLogin();
    const me = await res.json();
    enterApp(me);
  } catch {
    showLogin();
  }
}

function enterApp(me) {
  state.me = me;
  $('#boot').classList.add('hidden');
  $('#login-view').classList.add('hidden');
  $('#app-view').classList.remove('hidden');
  $('#side-version').textContent = 'v' + me.version;
  $('#side-user').textContent = me.role === 'admin' ? '管理员' : me.email;

  const isAdmin = me.role === 'admin';
  $$('#nav .nav-item').forEach((btn) => {
    const page = btn.dataset.page;
    if (page === 'my') btn.classList.toggle('hidden', isAdmin);
    else btn.classList.toggle('hidden', !isAdmin);
  });

  if (!isAdmin) {
    navigate('my');
  } else {
    navigate('overview');
  }
}

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const token = $('#admin-token').value.trim();
  $('#login-error').textContent = '';
  try {
    await api('/api/login', { method: 'POST', body: { token } });
    const me = await api('/api/me');
    enterApp(me);
  } catch (err) {
    $('#login-error').textContent = err.message;
  }
});

$('#google-login').addEventListener('click', () => {
  location.href = '/auth/google/start?next=/';
});

$('#logout').addEventListener('click', async () => {
  try {
    await api('/api/logout', { method: 'POST' });
  } catch {}
  location.reload();
});

/* -------------------------------- navigation ------------------------------- */

function navigate(page) {
  state.page = page;
  $$('#nav .nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $$('.page').forEach((p) => p.classList.add('hidden'));
  const el = $('#page-' + page);
  if (el) el.classList.remove('hidden');

  const titles = { overview: '概览', accounts: '账号池', models: '模型', keys: 'API Keys', settings: '设置', my: '我的 Key' };
  $('#page-title').textContent = titles[page] || '';

  stopRefresh();
  if (page === 'overview') loadOverview();
  if (page === 'accounts') loadAccounts();
  if (page === 'models') loadModels();
  if (page === 'keys') loadKeys();
  if (page === 'settings') loadSettings();
  if (page === 'my') loadMyKeys();

  if (['overview', 'accounts'].includes(page)) {
    state.refreshTimer = setInterval(() => {
      if (document.hidden || $('#modal-root').children.length) return;
      if (page === 'overview') loadOverview(true);
      if (page === 'accounts') loadAccounts(true);
    }, 8000);
  }
}

function stopRefresh() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = null;
}

$$('#nav .nav-item').forEach((btn) => btn.addEventListener('click', () => navigate(btn.dataset.page)));

/* --------------------------------- overview -------------------------------- */

async function loadOverview(silent = false) {
  try {
    const data = await api('/api/overview');
    const s = data.summary;
    state.baseUrl = data.server.baseUrl;
    $('#s-total').textContent = s.total;
    $('#s-enabled').textContent = `${s.enabled} 个已启用`;
    $('#s-available').textContent = s.available;
    $('#s-cooldown').textContent = s.cooldown ? `${s.cooldown} 个冷却中` : '无冷却';
    $('#s-requests').textContent = fmtNum(s.requests);
    $('#s-errors').textContent = `${s.errors} 次错误`;
    $('#s-tokens').textContent = fmtNum(s.inputTokens + s.outputTokens);
    $('#s-keys').textContent = `${data.keys} 个 Key · ${data.users} 个用户`;
    $('#base-url').textContent = data.server.baseUrl;
    $('#routing-strategy').value = data.routing.strategy;
    $('#top-status').textContent = `账号 ${s.available}/${s.total} 可用`;

    const list = $('#error-list');
    if (!data.recentErrors.length) {
      list.innerHTML = '<div class="empty">暂无异常</div>';
      $('#err-count').textContent = '';
    } else {
      $('#err-count').textContent = data.recentErrors.length + ' 条';
      list.innerHTML = data.recentErrors
        .map(
          (e) => `<div class="row" style="justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-soft)">
            <div><div class="cell-main">${esc(e.email || e.label || e.id)}</div><div class="cell-sub">${esc(e.lastError)}</div></div>
            <span class="badge ${statusOf(e).cls}">${statusOf(e).text}</span>
          </div>`
        )
        .join('');
    }
  } catch (err) {
    if (!silent) toast(err.message, 'err');
  }
}

$('#save-routing').addEventListener('click', async () => {
  try {
    await api('/api/settings', { method: 'PATCH', body: { routing: { strategy: $('#routing-strategy').value } } });
    toast('路由策略已保存', 'ok');
    loadOverview();
  } catch (err) {
    toast(err.message, 'err');
  }
});

/* --------------------------------- accounts -------------------------------- */

async function loadAccounts(silent = false) {
  try {
    const data = await api('/api/accounts');
    state.accounts = data.accounts;
    state.proxySlots = data.proxySlots || [];
    state.localImportSupported = data.localImportSupported !== false;
    $('#import-local').classList.toggle('hidden', !state.localImportSupported);
    $('#accounts-hint').textContent = data.accounts.length ? `${data.accounts.length} 个账号` : '';
    renderAccounts(data.accounts);
    $('#top-status').textContent = `账号 ${data.summary.available}/${data.summary.total} 可用`;
  } catch (err) {
    if (!silent) toast(err.message, 'err');
  }
}

function renderAccounts(accounts) {
  const body = $('#accounts-body');
  if (!accounts.length) {
    body.innerHTML = '<tr><td colspan="7"><div class="empty">还没有账号。可用 Google 授权添加，或点击「添加账号」粘贴 Token。</div></td></tr>';
    return;
  }
  body.innerHTML = accounts
    .map((acc) => {
      const st = statusOf(acc);
      const tokens = (acc.stats?.inputTokens || 0) + (acc.stats?.outputTokens || 0);
      return `<tr data-id="${esc(acc.id)}">
        <td>
          <div class="cell-main">${esc(acc.email || acc.label || acc.id)}</div>
          <div class="cell-sub mono">${esc(acc.tokenPreview)}</div>
        </td>
        <td><span class="badge ${st.cls}"><span class="dot ${st.dot}"></span>${st.text}</span></td>
        <td>${acc.proxySlotId ? esc(acc.proxySlotName || '绑定节点已移除') : acc.proxy ? '<span class="muted small">自定义代理</span>' : '<span class="muted small">直连</span>'}</td>
        <td class="num">${fmtNum(acc.stats?.requests)}</td>
        <td class="num">${fmtNum(tokens)}</td>
        <td class="muted small">${fmtTime(acc.stats?.lastUsedAt)}</td>
        <td>
          <div class="actions">
            <button class="btn btn-ghost small" data-act="test">测试</button>
            <button class="btn btn-ghost small" data-act="edit">编辑</button>
            <button class="btn btn-danger small" data-act="del">删除</button>
          </div>
        </td>
      </tr>`;
    })
    .join('');

  $$('#accounts-body tr').forEach((tr) => {
    const id = tr.dataset.id;
    tr.addEventListener('click', async (e) => {
      const act = e.target.closest('button')?.dataset.act;
      if (!act) return;
      const acc = state.accounts.find((a) => a.id === id);
      if (act === 'edit') openEditAccount(acc);
      if (act === 'test') testAccount(acc);
      if (act === 'del') deleteAccount(acc);
    });
  });
}

async function testAccount(acc) {
  toast('正在测试 ' + (acc.email || acc.id) + ' …');
  try {
    const r = await api(`/api/accounts/${acc.id}/test`, { method: 'POST' });
    if (r.ok) toast(`连接正常 · ${r.latencyMs}ms`, 'ok');
    else toast('测试失败：' + r.error, 'err');
    loadAccounts(true);
  } catch (err) {
    toast(err.message, 'err');
  }
}

async function deleteAccount(acc) {
  if (!confirm(`确定删除账号 ${acc.email || acc.id} 吗？`)) return;
  try {
    await api(`/api/accounts/${acc.id}`, { method: 'DELETE' });
    toast('已删除', 'ok');
    loadAccounts();
  } catch (err) {
    toast(err.message, 'err');
  }
}

function proxyFields(prefix, acc = {}) {
  const selected = acc.proxySlotId || (acc.proxy ? 'manual' : '');
  const slots = [...state.proxySlots];
  if (acc.proxySlotId && !slots.some((s) => s.id === acc.proxySlotId)) {
    slots.push({ id: acc.proxySlotId, name: '原绑定节点已移除', enabled: false });
  }
  const options = [{ id: '', name: '直连（不使用代理）', enabled: true },
    { id: 'manual', name: '自定义 HTTP / SOCKS5 代理', enabled: true }, ...slots];
  return `<label class="field"><span>此账号的出口代理</span><select class="input" id="${prefix}-proxy-slot">
    ${options.map((s) => `<option value="${esc(s.id)}" ${s.id === selected ? 'selected' : ''} ${s.enabled ? '' : 'disabled'}>${esc(s.name)}${s.enabled ? '' : '（停用）'}</option>`).join('')}
    </select></label><label class="field ${selected === 'manual' ? '' : 'hidden'}" id="${prefix}-proxy-field">
    <span>自定义代理地址</span><input class="input" id="${prefix}-proxy" value="${esc(acc.proxy || '')}" placeholder="http://user:pass@host:port 或 socks5://host:port" /></label>
    <div class="muted small">订阅节点固定绑定到此账号；节点不可用时不会改为直连。修改后请先保存，再测试。</div>`;
}

function bindProxyFields(prefix) {
  $(`#${prefix}-proxy-slot`).addEventListener('change', (e) => {
    $(`#${prefix}-proxy-field`).classList.toggle('hidden', e.target.value !== 'manual');
  });
}

function proxyBody(prefix) {
  const slot = $(`#${prefix}-proxy-slot`).value;
  return { proxySlotId: slot === 'manual' ? '' : slot, proxy: slot === 'manual' ? $(`#${prefix}-proxy`).value : '' };
}

function openEditAccount(acc) {
  const st = statusOf(acc);
  const html = `
    <div class="modal-mask" id="modal-mask">
      <div class="modal">
        <div class="modal-head"><h3>编辑账号</h3><button class="modal-close" data-close>×</button></div>
        <div class="modal-body">
          <div class="row" style="justify-content:space-between">
            <div><div class="cell-main">${esc(acc.email || acc.id)}</div><div class="cell-sub">过期时间：${esc(acc.expText)}</div></div>
            <span class="badge ${st.cls}"><span class="dot ${st.dot}"></span>${st.text}</span>
          </div>
          <label class="field"><span>备注名称</span><input class="input" id="edit-label" value="${esc(acc.label || '')}" /></label>
          ${proxyFields('edit', acc)}
          <label class="check"><input type="checkbox" id="edit-enabled" ${acc.enabled ? 'checked' : ''} /> 启用该账号</label>
          <div class="row">
            <button class="btn btn-ghost small" id="edit-test">测试连接</button>
            <button class="btn btn-ghost small" id="edit-refresh">刷新 Token</button>
            <button class="btn btn-ghost small" id="edit-reset">清除冷却</button>
            <span class="spacer"></span>
            <span class="muted small" id="edit-msg"></span>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" data-close>取消</button>
          <button class="btn btn-primary" id="edit-save">保存</button>
        </div>
      </div>
    </div>`;
  openModal(html);
  bindProxyFields('edit');
  $('#edit-test').addEventListener('click', async () => {
    $('#edit-msg').textContent = '测试中…';
    try {
      const r = await api(`/api/accounts/${acc.id}/test`, { method: 'POST' });
      $('#edit-msg').textContent = r.ok ? `正常 · ${r.latencyMs}ms` : r.error;
      if (r.ok) toast('连接正常', 'ok');
    } catch (err) {
      $('#edit-msg').textContent = err.message;
    }
  });
  $('#edit-refresh').addEventListener('click', async () => {
    $('#edit-msg').textContent = '刷新中…';
    try {
      const r = await api(`/api/accounts/${acc.id}/refresh`, { method: 'POST' });
      $('#edit-msg').textContent = r.ok ? '已刷新' : r.error;
      if (r.ok) toast('Token 已刷新', 'ok');
    } catch (err) {
      $('#edit-msg').textContent = err.message;
    }
  });
  $('#edit-reset').addEventListener('click', async () => {
    try {
      await api(`/api/accounts/${acc.id}/reset`, { method: 'POST' });
      toast('冷却已清除', 'ok');
      closeModal();
      loadAccounts();
    } catch (err) {
      toast(err.message, 'err');
    }
  });
  $('#edit-save').addEventListener('click', async () => {
    try {
      await api(`/api/accounts/${acc.id}`, {
        method: 'PATCH',
        body: {
          label: $('#edit-label').value,
          ...proxyBody('edit'),
          enabled: $('#edit-enabled').checked,
        },
      });
      toast('已保存', 'ok');
      closeModal();
      loadAccounts();
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

/* ------------------------------- add account ------------------------------- */

$('#add-account').addEventListener('click', openAddAccount);

function openAddAccount() {
  const html = `
    <div class="modal-mask" id="modal-mask">
      <div class="modal">
        <div class="modal-head"><h3>添加账号</h3><button class="modal-close" data-close>×</button></div>
        <div class="tabs">
          <button class="tab active" data-tab="local">本机导入</button>
          <button class="tab" data-tab="token">粘贴 Token</button>
          <button class="tab" data-tab="login">官方登录</button>
        </div>
        <div class="modal-body">
          <div class="tab-panel" data-panel="local">
            <div class="hint-box">读取 <code>%LOCALAPPDATA%\\IrisGo\\profiles\\*\\data\\app.sqlite</code> 里的登录凭据。只读，不会修改 IrisGo 的数据。</div>
            <div class="local-list" id="local-list"><div class="empty">正在扫描…</div></div>
            <div class="row">
              <button class="btn btn-primary" id="import-all">全部导入</button>
              <button class="btn btn-ghost" id="rescan">重新扫描</button>
              <span class="spacer"></span>
              <span class="muted small" id="local-msg"></span>
            </div>
          </div>

          <div class="tab-panel hidden" data-panel="token">
            <div class="hint-box">从 IrisGo 的 <code>app.sqlite</code> → <code>secrets</code> 表 → <code>auth.irisgo</code> 复制 <code>token</code> 字段，粘贴到这里。</div>
            <label class="field"><span>Access Token</span><textarea class="input" id="add-token" placeholder="eyJhbGciOiJIUzI1NiIs..."></textarea></label>
            <label class="field"><span>备注（可选）</span><input class="input" id="add-label" placeholder="例如：账号 A" /></label>
            ${proxyFields('add')}
            <div class="row"><button class="btn btn-primary" id="add-submit">添加</button><span class="muted small" id="add-msg"></span></div>
          </div>

          <div class="tab-panel hidden" data-panel="login">
            <div class="hint-box">服务器网页登录可用，无需安装 IrisGo：在官方 Google 页面授权后，复制回调链接完成导入。</div>
            <p><a class="btn btn-primary" href="/irisgo-authorize.html" target="_blank" rel="noopener noreferrer">打开 Google 网页授权页</a></p>
            <div id="windows-login-options">
            <div class="hint-box">
              <b>方式一：网页登录（不需要安装 IrisGo）</b><br/>
              点「用 Google 登录」后会打开浏览器，授权完成后会自动跳回本机，账号直接进池。<br/>
              <span class="muted">原理：注册 <code>irisgo://</code> 协议处理器，接住 IrisGo 网页登录回跳的授权码，再由本机服务兑换成 token。不会动 IrisGo 安装的 <code>ai.irisgo://</code>。</span>
            </div>
            <div class="row">
              <button class="btn btn-primary" id="web-login">用 Google 登录</button>
              <span class="spacer"></span>
              <span class="muted small" id="web-login-msg"></span>
            </div>

            <div class="hint-box">
              <b>方式二：桌面端登录（已安装 IrisGo 时）</b><br/>
              启动 IrisGo，在应用里点「Sign in with Google」，登录成功后下面的列表会自动出现新账号并导入。
            </div>
            <div class="row">
              <button class="btn btn-ghost" id="open-irisgo">启动 IrisGo</button>
              <button class="btn btn-ghost" id="login-rescan">刷新列表</button>
              <span class="spacer"></span>
              <span class="muted small" id="login-msg">等待登录…</span>
            </div>
            <div class="local-list" id="login-list"><div class="empty">尚未发现新账号</div></div>
            </div>
          </div>
        </div>
        <div class="modal-foot"><button class="btn btn-ghost" data-close>关闭</button></div>
      </div>
    </div>`;
  openModal(html);
  bindProxyFields('add');

  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
      $$('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== tab.dataset.tab));
      if (tab.dataset.tab === 'login' && state.localImportSupported) startLoginWatch();
      else stopLoginWatch();
    });
  });

  const renderLocal = (data, targetId, showImport = true) => {
    const box = $('#' + targetId);
    if (!data.exists) {
      box.innerHTML = `<div class="empty">没有找到 IrisGo 数据目录：<br/><span class="mono">${esc(data.dir)}</span></div>`;
      return;
    }
    if (!data.accounts.length) {
      box.innerHTML = '<div class="empty">没有检测到已登录的 IrisGo 账号</div>';
      return;
    }
    box.innerHTML = data.accounts
      .map(
        (a) => `<div class="local-item">
          <div class="grow">
            <div class="email">${esc(a.email || a.userId)}</div>
            <div class="cell-sub">${a.isActive ? '当前登录 · ' : ''}有效期至 ${esc(a.expText)}${a.known ? ' · 已在池中' : ''}</div>
          </div>
          <span class="badge ${a.valid ? 'ok' : 'err'}">${a.valid ? '有效' : '已过期'}</span>
          ${showImport && !a.known ? `<button class="btn btn-ghost small" data-import="${esc(a.userId)}">导入</button>` : ''}
        </div>`
      )
      .join('');
  };

  const scan = async (targetId) => {
    try {
      const data = await api('/api/accounts/local-preview');
      renderLocal(data, targetId);
      return data;
    } catch (err) {
      $('#' + targetId).innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  };

  scan('local-list');

  const autoImported = new Set();

  const startLoginWatch = () => {
    if (state.loginWatch) return;
    const tick = async () => {
      const data = await scan('login-list');
      if (!data?.accounts) return;
      const fresh = data.accounts.filter((a) => !a.known && !autoImported.has(a.userId));
      if (!fresh.length) return;
      try {
        const r = await api('/api/accounts/import-local', { method: 'POST' });
        for (const a of fresh) autoImported.add(a.userId);
        if (r.imported) {
          toast(`已自动导入 ${r.imported} 个账号`, 'ok');
          loadAccounts(true);
          $('#login-msg').textContent = '已自动导入 ' + r.imported + ' 个账号';
        }
        scan('login-list');
      } catch (err) {
        $('#login-msg').textContent = err.message;
      }
    };
    tick();
    state.loginWatch = setInterval(tick, 3000);
  };

  const stopLoginWatch = () => {
    if (state.loginWatch) clearInterval(state.loginWatch);
    state.loginWatch = null;
  };

  $('#web-login').addEventListener('click', async () => {
    const btn = $('#web-login');
    btn.disabled = true;
    $('#web-login-msg').textContent = '正在打开浏览器…';
    const popup = window.open('about:blank', '_blank');
    try {
      const r = await api('/api/oauth/web/start', { method: 'POST' });
      if (!r.scheme || !r.scheme.ok) {
        $('#web-login-msg').textContent = '协议注册失败：' + ((r.scheme && r.scheme.error) || '未知错误');
        btn.disabled = false;
        if (popup) popup.close();
        return;
      }
      if (popup) popup.location.href = r.url;
      else window.location.href = r.url;
      $('#web-login-msg').textContent = '等待浏览器授权…';

      if (state.webLoginTimer) clearInterval(state.webLoginTimer);
      state.webLoginTimer = setInterval(async () => {
        try {
          const f = await api('/api/oauth/web/flow/' + r.flowId);
          if (f.status === 'ok') {
            clearInterval(state.webLoginTimer);
            state.webLoginTimer = null;
            $('#web-login-msg').textContent = '登录成功：' + (f.email || '');
            toast('账号已加入池子：' + (f.email || ''), 'ok');
            loadAccounts(true);
            setTimeout(closeModal, 900);
          } else if (f.status === 'error' || f.status === 'expired') {
            clearInterval(state.webLoginTimer);
            state.webLoginTimer = null;
            $('#web-login-msg').textContent = f.error || '登录失败';
            btn.disabled = false;
          }
        } catch (err) {
          clearInterval(state.webLoginTimer);
          state.webLoginTimer = null;
          $('#web-login-msg').textContent = err.message;
          btn.disabled = false;
        }
      }, 1500);
    } catch (err) {
      $('#web-login-msg').textContent = err.message;
      btn.disabled = false;
      if (popup) popup.close();
    }
  });

  $('#rescan').addEventListener('click', () => scan('local-list'));
  $('#login-rescan').addEventListener('click', () => startLoginWatch());

  $('#import-all').addEventListener('click', async () => {
    try {
      const r = await api('/api/accounts/import-local', { method: 'POST' });
      $('#local-msg').textContent = `新增 ${r.imported}，更新 ${r.updated}`;
      toast(`导入完成：新增 ${r.imported}，更新 ${r.updated}`, 'ok');
      scan('local-list');
      loadAccounts(true);
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  $('#add-submit').addEventListener('click', async () => {
    const token = $('#add-token').value.trim();
    if (!token) return ($('#add-msg').textContent = '请先粘贴 token');
    $('#add-msg').textContent = '校验中…';
    try {
      const r = await api('/api/accounts', {
        method: 'POST',
        body: { token, label: $('#add-label').value, ...proxyBody('add') },
      });
      toast(r.updated ? '账号已更新' : '账号已添加', 'ok');
      closeModal();
      loadAccounts();
    } catch (err) {
      $('#add-msg').textContent = err.message;
    }
  });

  $('#open-irisgo').addEventListener('click', async () => {
    try {
      await api('/api/accounts/open-app', { method: 'POST' });
      toast('已启动 IrisGo，请在应用内完成 Google 登录', 'ok');
      $('#login-msg').textContent = '等待登录…';
      startLoginWatch();
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  if (!state.localImportSupported) {
    $$('.tab').forEach((t) => { t.classList.toggle('active', t.dataset.tab === 'token'); t.disabled = t.dataset.tab === 'local'; });
    $$('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== 'token'));
    $('#local-list').textContent = '服务器不支持 Windows 本机导入，请粘贴 Token。';
    $('#windows-login-options').classList.add('hidden');
  }

  $('#login-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-import]');
    if (!btn) return;
    try {
      const r = await api('/api/accounts/import-local', { method: 'POST' });
      toast(`已导入 ${r.imported} 个账号`, 'ok');
      scan('login-list');
      loadAccounts(true);
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

/* ---------------------------------- models --------------------------------- */

async function loadModels() {
  try {
    const data = await api('/api/models');
    state.models = {
      list: data.models,
      config: data.config,
      source: data.source,
      fetchedAt: data.fetchedAt,
      error: data.error,
    };
    $('#models-auto').checked = data.config.includeAuto !== false;
    $('#models-hint').textContent = `${data.visibleCount}/${data.total} 个已暴露 · 来源 ${data.source}`;
    renderModels();
    if (data.error) toast('模型目录获取失败，使用缓存：' + data.error, 'err');
  } catch (err) {
    toast(err.message, 'err');
  }
}

function fmtPrice(pricing) {
  if (!pricing || (!pricing.prompt && !pricing.completion)) return '免费';
  const f = (n) => {
    const v = n * 1e6;
    if (!v) return '0';
    return v < 0.1 ? v.toFixed(3) : v.toFixed(2);
  };
  return `$${f(pricing.prompt)} / $${f(pricing.completion)}`;
}

function renderModels() {
  const q = ($('#model-search').value || '').trim().toLowerCase();
  const list = (state.models?.list || []).filter(
    (m) => !q || m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q)
  );
  const body = $('#models-body');
  if (!list.length) {
    body.innerHTML = '<tr><td colspan="5"><div class="empty">没有匹配的模型</div></td></tr>';
    return;
  }
  body.innerHTML = list
    .map(
      (m) => `<tr data-id="${esc(m.id)}">
        <td><input type="checkbox" class="model-toggle" ${m.visible ? 'checked' : ''} /></td>
        <td><span class="mono">${esc(m.id)}</span></td>
        <td>${esc(m.name)}</td>
        <td class="num">${m.context_length ? fmtNum(m.context_length) : '—'}</td>
        <td class="num">${fmtPrice(m.pricing)}</td>
      </tr>`
    )
    .join('');

  $$('#models-body .model-toggle').forEach((cb) => {
    cb.addEventListener('change', async (e) => {
      const id = e.target.closest('tr').dataset.id;
      await setModelVisible(id, e.target.checked);
    });
  });
}

async function setModelVisible(id, visible) {
  const hidden = new Set(state.models.config.hidden || []);
  if (visible) hidden.delete(id);
  else hidden.add(id);
  state.models.config.hidden = [...hidden];
  state.models.list = state.models.list.map((m) => (m.id === id ? { ...m, visible } : m));
  try {
    await api('/api/models', { method: 'PATCH', body: { hidden: [...hidden] } });
    const visibleCount = state.models.list.filter((m) => m.visible).length + (state.models.config.includeAuto !== false ? 1 : 0);
    $('#models-hint').textContent = `${visibleCount}/${state.models.list.length} 个已暴露 · 来源 ${state.models.source}`;
  } catch (err) {
    toast(err.message, 'err');
  }
}

$('#model-search').addEventListener('input', () => renderModels());

$('#models-refresh').addEventListener('click', async () => {
  try {
    const r = await api('/api/models', { method: 'PATCH', body: { refresh: true } });
    toast(`已刷新：${r.total} 个模型（${r.source}）`, 'ok');
    loadModels();
  } catch (err) {
    toast(err.message, 'err');
  }
});

$('#models-show-all').addEventListener('click', async () => {
  try {
    await api('/api/models', { method: 'PATCH', body: { hidden: [] } });
    loadModels();
  } catch (err) {
    toast(err.message, 'err');
  }
});

$('#models-hide-all').addEventListener('click', async () => {
  if (!confirm('隐藏所有具体模型，只保留 auto？')) return;
  try {
    await api('/api/models', {
      method: 'PATCH',
      body: { hidden: (state.models?.list || []).map((m) => m.id) },
    });
    loadModels();
  } catch (err) {
    toast(err.message, 'err');
  }
});

$('#models-auto').addEventListener('change', async (e) => {
  try {
    await api('/api/models', { method: 'PATCH', body: { includeAuto: e.target.checked } });
    loadModels();
  } catch (err) {
    toast(err.message, 'err');
  }
});

/* ----------------------------------- keys ---------------------------------- */

async function loadKeys() {
  try {
    const [keys, accounts] = await Promise.all([api('/api/keys'), api('/api/accounts')]);
    state.keys = keys.keys;
    state.accounts = accounts.accounts;
    renderKeys(keys.keys);
    $('#curl-example').textContent = curlExample(state.baseUrl);
  } catch (err) {
    toast(err.message, 'err');
  }
}

function renderKeys(keys) {
  const body = $('#keys-body');
  if (!keys.length) {
    body.innerHTML = '<tr><td colspan="7"><div class="empty">还没有 API Key，点击「创建 Key」生成一个。</div></td></tr>';
    return;
  }
  body.innerHTML = keys
    .map((k) => {
      const acc = state.accounts.find((a) => a.id === k.accountId);
      return `<tr data-id="${esc(k.id)}">
        <td><div class="cell-main">${esc(k.name)}</div><div class="cell-sub">${fmtTime(k.createdAt)}</div></td>
        <td><span class="mono">${esc(k.prefix)}</span></td>
        <td>${acc ? esc(acc.email || acc.label) : '<span class="muted small">自动分配</span>'}</td>
        <td class="num">${k.rpm || '不限'}</td>
        <td><span class="badge ${k.enabled ? 'ok' : 'off'}"><span class="dot ${k.enabled ? 'ok' : 'off'}"></span>${k.enabled ? '启用' : '停用'}</span></td>
        <td class="num">${fmtNum(k.stats?.requests)}</td>
        <td>
          <div class="actions">
            <button class="btn btn-ghost small" data-act="toggle">${k.enabled ? '停用' : '启用'}</button>
            <button class="btn btn-danger small" data-act="del">删除</button>
          </div>
        </td>
      </tr>`;
    })
    .join('');

  $$('#keys-body tr').forEach((tr) => {
    const id = tr.dataset.id;
    tr.addEventListener('click', async (e) => {
      const act = e.target.closest('button')?.dataset.act;
      if (!act) return;
      const key = state.keys.find((k) => k.id === id);
      if (act === 'toggle') {
        await api(`/api/keys/${id}`, { method: 'PATCH', body: { enabled: !key.enabled } });
        loadKeys();
      }
      if (act === 'del') {
        if (!confirm('确定删除这个 Key 吗？')) return;
        await api(`/api/keys/${id}`, { method: 'DELETE' });
        toast('已删除', 'ok');
        loadKeys();
      }
    });
  });
}

$('#add-key').addEventListener('click', () => {
  const options = ['<option value="">自动分配（账号池）</option>']
    .concat(state.accounts.map((a) => `<option value="${esc(a.id)}">${esc(a.email || a.label || a.id)}</option>`))
    .join('');
  const html = `
    <div class="modal-mask" id="modal-mask">
      <div class="modal">
        <div class="modal-head"><h3>创建 API Key</h3><button class="modal-close" data-close>×</button></div>
        <div class="modal-body">
          <label class="field"><span>名称</span><input class="input" id="key-name" placeholder="例如：我的笔记本" /></label>
          <label class="field"><span>绑定账号</span><select class="select" id="key-account">${options}</select></label>
          <label class="field"><span>每分钟请求上限（0 = 不限）</span><input class="input" id="key-rpm" type="number" min="0" value="0" /></label>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" data-close>取消</button>
          <button class="btn btn-primary" id="key-create">创建</button>
        </div>
      </div>
    </div>`;
  openModal(html);
  $('#key-create').addEventListener('click', async () => {
    try {
      const r = await api('/api/keys', {
        method: 'POST',
        body: { name: $('#key-name').value, accountId: $('#key-account').value || null, rpm: Number($('#key-rpm').value) || 0 },
      });
      closeModal();
      showSecret(r.secret);
      loadKeys();
    } catch (err) {
      toast(err.message, 'err');
    }
  });
});

function showSecret(secret) {
  const html = `
    <div class="modal-mask" id="modal-mask">
      <div class="modal">
        <div class="modal-head"><h3>Key 已创建</h3><button class="modal-close" data-close>×</button></div>
        <div class="modal-body">
          <div class="hint-box">只显示这一次，请立即复制保存。</div>
          <div class="copy-row"><code id="secret-value">${esc(secret)}</code><button class="btn btn-ghost small" data-copy="#secret-value">复制</button></div>
        </div>
        <div class="modal-foot"><button class="btn btn-primary" data-close>完成</button></div>
      </div>
    </div>`;
  openModal(html);
}

/* ---------------------------------- my keys -------------------------------- */

async function loadMyKeys() {
  try {
    const data = await api('/api/my/keys');
    const body = $('#my-keys-body');
    if (!data.keys.length) {
      body.innerHTML = '<tr><td colspan="6"><div class="empty">你还没有 Key，点击上方按钮创建一个。</div></td></tr>';
    } else {
      body.innerHTML = data.keys
        .map(
          (k) => `<tr data-id="${esc(k.id)}">
            <td><div class="cell-main">${esc(k.name)}</div><div class="cell-sub">${fmtTime(k.createdAt)}</div></td>
            <td><span class="mono">${esc(k.prefix)}</span></td>
            <td class="num">${k.rpm || '不限'}</td>
            <td><span class="badge ${k.enabled ? 'ok' : 'off'}">${k.enabled ? '启用' : '停用'}</span></td>
            <td class="num">${fmtNum(k.stats?.requests)}</td>
            <td><div class="actions"><button class="btn btn-danger small" data-act="del">删除</button></div></td>
          </tr>`
        )
        .join('');
      $$('#my-keys-body tr').forEach((tr) => {
        tr.addEventListener('click', async (e) => {
          if (e.target.closest('button')?.dataset.act !== 'del') return;
          if (!confirm('确定删除这个 Key 吗？')) return;
          await api(`/api/my/keys/${tr.dataset.id}`, { method: 'DELETE' });
          loadMyKeys();
        });
      });
    }
    $('#my-curl').textContent = curlExample(state.baseUrl, true);
  } catch (err) {
    toast(err.message, 'err');
  }
}

$('#add-my-key').addEventListener('click', async () => {
  try {
    const r = await api('/api/my/keys', { method: 'POST', body: { name: state.me?.email || '我的 Key' } });
    showSecret(r.secret);
    loadMyKeys();
  } catch (err) {
    toast(err.message, 'err');
  }
});

/* --------------------------------- settings -------------------------------- */

async function loadSettings() {
  try {
    const s = await api('/api/settings');
    state.settings = s;
    state.baseUrl = s.server.baseUrl;
    $('#set-retries').value = s.routing.maxRetries;
    $('#set-cooldown').value = s.routing.cooldownSeconds;
    $('#set-timeout').value = s.routing.requestTimeoutMs;
    $('#set-google-id').value = s.google.clientId || '';
    $('#set-google-secret').value = '';
    $('#set-google-emails').value = (s.google.allowedEmails || []).join(', ');
    $('#set-google-domains').value = (s.google.allowedDomains || []).join(', ');
    $('#set-google-proxy').value = s.google.proxy || '';
    $('#set-google-enabled').checked = !!s.google.enabled;
    $('#set-google-auto').checked = !!s.google.autoProvision;
    $('#set-app-path').value = s.app.irisgoAppPath;
    $('#redirect-uri').textContent = s.google.redirectUri;
  } catch (err) {
    toast(err.message, 'err');
  }
}

$('#save-settings').addEventListener('click', async () => {
  try {
    await api('/api/settings', {
      method: 'PATCH',
      body: {
        routing: {
          maxRetries: Number($('#set-retries').value),
          cooldownSeconds: Number($('#set-cooldown').value),
          requestTimeoutMs: Number($('#set-timeout').value),
        },
        google: {
          enabled: $('#set-google-enabled').checked,
          clientId: $('#set-google-id').value,
          clientSecret: $('#set-google-secret').value,
          allowedEmails: $('#set-google-emails').value,
          allowedDomains: $('#set-google-domains').value,
          autoProvision: $('#set-google-auto').checked,
          proxy: $('#set-google-proxy').value,
        },
        app: { irisgoAppPath: $('#set-app-path').value },
      },
    });
    toast('设置已保存', 'ok');
    loadSettings();
  } catch (err) {
    toast(err.message, 'err');
  }
});

$('#rotate-token').addEventListener('click', async () => {
  if (!confirm('重置后旧令牌立即失效，需要重新登录。继续吗？')) return;
  try {
    const r = await api('/api/admin/rotate-token', { method: 'POST' });
    alert('新的管理员令牌（请保存）：\n\n' + r.token);
    location.reload();
  } catch (err) {
    toast(err.message, 'err');
  }
});

/* ---------------------------------- modal ---------------------------------- */

function openModal(html) {
  closeModal();
  $('#modal-root').innerHTML = html;
  document.body.style.overflow = 'hidden';
  $$('[data-close]').forEach((el) => el.addEventListener('click', closeModal));
  $('#modal-mask')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-mask') closeModal();
  });
  document.addEventListener('keydown', escClose);
}

function escClose(e) {
  if (e.key === 'Escape') closeModal();
}

function closeModal() {
  if (state.modalPoll) {
    clearInterval(state.modalPoll);
    state.modalPoll = null;
  }
  if (state.loginWatch) {
    clearInterval(state.loginWatch);
    state.loginWatch = null;
  }
  if (state.webLoginTimer) {
    clearInterval(state.webLoginTimer);
    state.webLoginTimer = null;
  }
  $('#modal-root').innerHTML = '';
  document.body.style.overflow = '';
  document.removeEventListener('keydown', escClose);
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-copy]');
  if (!btn) return;
  const target = $(btn.dataset.copy);
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.textContent.trim());
    toast('已复制', 'ok');
  } catch {
    toast('复制失败，请手动选择', 'err');
  }
});

/* ---------------------------------- utils ---------------------------------- */

function curlExample(baseUrl, mine = false) {
  return `curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer ${mine ? '你的 Key' : 'sk-ig-...'}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}],"stream":true}'`;
}

boot();
