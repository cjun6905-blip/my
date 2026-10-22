'use strict';

const fs = require('node:fs');
const { parseProxy } = require('./util');

class ProxySlots {
  constructor(file) { this.file = file; }

  read() {
    try {
      const rows = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (!Array.isArray(rows) || rows.some((r) => !r || typeof r.id !== 'string' || !r.id ||
        typeof r.name !== 'string' || typeof r.url !== 'string' || !parseProxy(r.url)) ||
        new Set(rows.map((r) => r.id)).size !== rows.length) throw new Error();
      return rows;
    } catch (err) {
      if (err.code === 'ENOENT') return [];
      throw Object.assign(new Error('代理节点目录不可用，请联系管理员'), { statusCode: 503 });
    }
  }

  list() { return this.read().map(({ id, name, enabled }) => ({ id, name, enabled: enabled !== false })); }

  resolve(account) {
    if (!account.proxySlotId) return account.proxy || '';
    const slot = this.read().find((r) => r.id === account.proxySlotId);
    if (!slot || slot.enabled === false) {
      throw Object.assign(new Error('账号绑定的代理节点不存在或已停用，请重新选择'), { statusCode: 400 });
    }
    return slot.url;
  }

  binding(body, current = {}) {
    if (body.proxySlotId === undefined && body.proxy === undefined) {
      return { proxy: current.proxy || '', proxySlotId: current.proxySlotId || '' };
    }
    const result = { proxy: '', proxySlotId: String(body.proxySlotId || '') };
    if (!result.proxySlotId) {
      result.proxy = String(body.proxy || '').trim();
      try { parseProxy(result.proxy); }
      catch { throw Object.assign(new Error('代理格式无效，请使用 HTTP 或 SOCKS5 URL'), { statusCode: 400 }); }
    }
    this.resolve(result);
    return result;
  }
}

module.exports = { ProxySlots };
