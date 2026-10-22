'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { uid, nowSec } = require('./util');

function defaults() {
  return {
    version: 1,
    createdAt: nowSec(),
    server: {
      host: '127.0.0.1',
      port: 8787,
      publicBaseUrl: '',
    },
    admin: {
      token: 'igp_' + crypto.randomBytes(24).toString('hex'),
      sessionSecret: crypto.randomBytes(32).toString('hex'),
      createdAt: nowSec(),
    },
    google: {
      enabled: false,
      clientId: '',
      clientSecret: '',
      allowedEmails: [],
      allowedDomains: [],
      autoProvision: true,
    },
    routing: {
      strategy: 'round_robin',
      maxRetries: 2,
      cooldownSeconds: 60,
      requestTimeoutMs: 300000,
      defaultModel: 'auto',
    },
    settings: {
      irisgoAppPath: 'F:\\IrisGo\\IrisGo.exe',
    },
    deeplink: {
      secret: crypto.randomBytes(24).toString('hex'),
      scheme: 'irisgo',
      registeredCommand: '',
      registeredAt: 0,
    },
    models: {
      includeAuto: true,
      hidden: [],
      only: [],
    },
    accounts: [],
    keys: [],
    users: [],
  };
}

class Store {
  constructor(file) {
    this.file = file;
    this.data = defaults();
    this._saveTimer = null;
    this._saving = false;
  }

  load() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    if (!fs.existsSync(this.file)) {
      this.saveNow();
      return { created: true };
    }
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.data = this._migrate(raw);
    } catch (err) {
      const backup = this.file + '.broken-' + Date.now();
      try {
        fs.copyFileSync(this.file, backup);
      } catch {}
      this.data = defaults();
      this.saveNow();
      return { created: true, recovered: true, backup, error: err.message };
    }
    return { created: false };
  }

  _migrate(raw) {
    const base = defaults();
    const data = {
      ...base,
      ...raw,
      server: { ...base.server, ...(raw.server || {}) },
      admin: { ...base.admin, ...(raw.admin || {}) },
      google: { ...base.google, ...(raw.google || {}) },
      routing: { ...base.routing, ...(raw.routing || {}) },
      settings: { ...base.settings, ...(raw.settings || {}) },
      deeplink: { ...base.deeplink, ...(raw.deeplink || {}) },
      models: { ...base.models, ...(raw.models || {}) },
      accounts: Array.isArray(raw.accounts) ? raw.accounts : [],
      keys: Array.isArray(raw.keys) ? raw.keys : [],
      users: Array.isArray(raw.users) ? raw.users : [],
    };
    for (const account of data.accounts) {
      account.stats = account.stats || { requests: 0, inputTokens: 0, outputTokens: 0, errors: 0 };
      if (typeof account.enabled !== 'boolean') account.enabled = true;
    }
    for (const key of data.keys) {
      key.stats = key.stats || { requests: 0 };
      if (typeof key.enabled !== 'boolean') key.enabled = true;
    }
    return data;
  }

  save() {
    if (this._saveTimer) return;
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      this.saveNow();
    }, 150);
    if (this._saveTimer.unref) this._saveTimer.unref();
  }

  saveNow() {
    if (this._saving) return;
    this._saving = true;
    try {
      const tmp = this.file + '.tmp-' + process.pid;
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2), 'utf8');
      fs.renameSync(tmp, this.file);
    } finally {
      this._saving = false;
    }
  }

  get accounts() {
    return this.data.accounts;
  }

  get keys() {
    return this.data.keys;
  }

  findAccount(id) {
    return this.data.accounts.find((a) => a.id === id) || null;
  }

  findAccountByUser(userId) {
    return this.data.accounts.find((a) => a.userId && a.userId === userId) || null;
  }

  addAccount(partial) {
    const account = {
      id: 'acc_' + uid(6),
      label: '',
      email: '',
      userId: '',
      token: '',
      refreshToken: '',
      exp: 0,
      proxy: '',
      enabled: true,
      weight: 1,
      status: 'ok',
      lastError: '',
      cooldownUntil: 0,
      needsRelogin: false,
      source: 'manual',
      createdAt: nowSec(),
      updatedAt: nowSec(),
      stats: { requests: 0, inputTokens: 0, outputTokens: 0, errors: 0, lastUsedAt: 0, lastLatencyMs: 0 },
      ...partial,
    };
    this.data.accounts.push(account);
    this.save();
    return account;
  }

  updateAccount(id, patch) {
    const account = this.findAccount(id);
    if (!account) return null;
    Object.assign(account, patch, { updatedAt: nowSec() });
    this.save();
    return account;
  }

  removeAccount(id) {
    const idx = this.data.accounts.findIndex((a) => a.id === id);
    if (idx === -1) return false;
    this.data.accounts.splice(idx, 1);
    for (const key of this.data.keys) {
      if (key.accountId === id) key.accountId = null;
    }
    this.save();
    return true;
  }

  findKeyByHash(hash) {
    return this.data.keys.find((k) => k.hash === hash) || null;
  }

  addKey(partial) {
    const key = {
      id: 'key_' + uid(6),
      name: '',
      hash: '',
      prefix: '',
      enabled: true,
      accountId: null,
      rpm: 0,
      owner: null,
      createdAt: nowSec(),
      lastUsedAt: 0,
      stats: { requests: 0 },
      ...partial,
    };
    this.data.keys.push(key);
    this.save();
    return key;
  }

  updateKey(id, patch) {
    const key = this.data.keys.find((k) => k.id === id);
    if (!key) return null;
    Object.assign(key, patch);
    this.save();
    return key;
  }

  removeKey(id) {
    const idx = this.data.keys.findIndex((k) => k.id === id);
    if (idx === -1) return false;
    this.data.keys.splice(idx, 1);
    this.save();
    return true;
  }

  upsertUser(profile) {
    let user = this.data.users.find((u) => u.sub === profile.sub);
    if (!user) {
      user = {
        sub: profile.sub,
        email: profile.email,
        name: profile.name || '',
        picture: profile.picture || '',
        createdAt: nowSec(),
        lastLoginAt: nowSec(),
      };
      this.data.users.push(user);
    } else {
      Object.assign(user, {
        email: profile.email || user.email,
        name: profile.name || user.name,
        picture: profile.picture || user.picture,
        lastLoginAt: nowSec(),
      });
    }
    this.save();
    return user;
  }
}

module.exports = { Store, defaults };
