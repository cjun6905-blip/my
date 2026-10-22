'use strict';

const { nowSec } = require('./util');

class Pool {
  constructor(store, logger) {
    this.store = store;
    this.log = logger;
    this.cursor = 0;
  }

  all() {
    return this.store.data.accounts;
  }

  isAvailable(account, now = Date.now()) {
    if (!account || !account.enabled) return false;
    if (account.needsRelogin) return false;
    if (account.cooldownUntil && account.cooldownUntil > now) return false;
    return true;
  }

  available() {
    return this.all().filter((a) => this.isAvailable(a));
  }

  pick({ exclude = new Set(), accountId = null } = {}) {
    if (accountId) {
      const bound = this.store.findAccount(accountId);
      if (!bound) return null;
      if (!this.isAvailable(bound)) return null;
      return bound;
    }
    const list = this.available().filter((a) => !exclude.has(a.id));
    if (!list.length) return null;

    const strategy = this.store.data.routing.strategy || 'round_robin';
    if (strategy === 'least_used') {
      list.sort((a, b) => (a.stats?.requests || 0) - (b.stats?.requests || 0));
      return list[0];
    }
    if (strategy === 'random') {
      return list[Math.floor(Math.random() * list.length)];
    }
    list.sort((a, b) => String(a.id).localeCompare(String(b.id)));
    const picked = list[this.cursor % list.length];
    this.cursor = (this.cursor + 1) % 1_000_003;
    return picked;
  }

  markUsed(account) {
    if (!account) return;
    const stats = (account.stats = account.stats || { requests: 0, inputTokens: 0, outputTokens: 0, errors: 0 });
    stats.requests += 1;
    stats.lastUsedAt = nowSec();
    this.store.save();
  }

  markTokens(account, usage) {
    if (!account || !usage) return;
    const stats = (account.stats = account.stats || { requests: 0, inputTokens: 0, outputTokens: 0, errors: 0 });
    stats.inputTokens = (stats.inputTokens || 0) + (usage.input || 0);
    stats.outputTokens = (stats.outputTokens || 0) + (usage.output || 0);
    this.store.save();
  }

  markSuccess(account, usage) {
    if (!account) return;
    const stats = (account.stats = account.stats || {
      requests: 0,
      inputTokens: 0,
      outputTokens: 0,
      errors: 0,
    });
    stats.requests += 1;
    stats.lastUsedAt = nowSec();
    if (usage) {
      stats.inputTokens += usage.input || 0;
      stats.outputTokens += usage.output || 0;
    }
    account.status = 'ok';
    account.lastError = '';
    account.cooldownUntil = 0;
    account.needsRelogin = false;
    this.store.save();
  }

  markLatency(account, ms) {
    if (!account) return;
    account.stats = account.stats || {};
    account.stats.lastLatencyMs = ms;
  }

  markCooldown(account, seconds, reason, status = 'cooldown') {
    if (!account) return;
    const stats = (account.stats = account.stats || { requests: 0, errors: 0 });
    stats.errors += 1;
    account.status = status;
    account.lastError = reason || '';
    account.cooldownUntil = Date.now() + Math.max(1, seconds) * 1000;
    this.store.save();
    this.log?.warn(`账号 ${account.email || account.id} 冷却 ${seconds}s：${reason}`);
  }

  markAuthFail(account, httpStatus) {
    if (!account) return;
    account.status = 'auth';
    account.needsRelogin = true;
    account.lastError = `认证失败（HTTP ${httpStatus}），请重新导入或登录`;
    account.cooldownUntil = Date.now() + 3600 * 1000;
    account.stats = account.stats || { requests: 0, errors: 0 };
    account.stats.errors += 1;
    this.store.save();
    this.log?.warn(`账号 ${account.email || account.id} 认证失败（HTTP ${httpStatus}）`);
  }

  markNetworkError(account, message) {
    this.markCooldown(account, 15, '网络错误：' + message, 'error');
  }

  reset(id) {
    const account = id ? this.store.findAccount(id) : null;
    const targets = account ? [account] : this.all();
    for (const a of targets) {
      a.status = 'ok';
      a.lastError = '';
      a.cooldownUntil = 0;
    }
    this.store.save();
  }

  summary() {
    const now = Date.now();
    const accounts = this.all();
    return {
      total: accounts.length,
      enabled: accounts.filter((a) => a.enabled).length,
      available: accounts.filter((a) => this.isAvailable(a, now)).length,
      auth: accounts.filter((a) => a.needsRelogin).length,
      cooldown: accounts.filter((a) => a.cooldownUntil > now).length,
      requests: accounts.reduce((n, a) => n + (a.stats?.requests || 0), 0),
      inputTokens: accounts.reduce((n, a) => n + (a.stats?.inputTokens || 0), 0),
      outputTokens: accounts.reduce((n, a) => n + (a.stats?.outputTokens || 0), 0),
      errors: accounts.reduce((n, a) => n + (a.stats?.errors || 0), 0),
    };
  }
}

module.exports = { Pool };
