'use strict';

const net = require('node:net');
const tls = require('node:tls');
const dns = require('node:dns');
const https = require('node:https');
const { parseProxy } = require('./util');

const agentCache = new Map();

function openProxySocket(proxy, timeoutMs) {
  return new Promise((resolve, reject) => {
    let socket;
    const onError = (err) => reject(err);
    if (proxy.protocol === 'https:') {
      socket = tls.connect({ host: proxy.host, port: proxy.port, servername: proxy.host });
      socket.once('secureConnect', () => resolve(socket));
    } else {
      socket = net.connect({ host: proxy.host, port: proxy.port });
      socket.once('connect', () => resolve(socket));
    }
    socket.setTimeout(timeoutMs || 20000, () => {
      socket.destroy();
      reject(new Error('连接代理超时：' + proxy.host + ':' + proxy.port));
    });
    socket.once('error', onError);
  });
}

async function httpConnect(proxy, host, port, timeoutMs) {
  const socket = await openProxySocket(proxy, timeoutMs);
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (err) => {
      if (settled) return;
      settled = true;
      socket.removeListener('data', onData);
      socket.setTimeout(0);
      if (err) {
        socket.destroy();
        reject(err);
      } else {
        resolve(socket);
      }
    };
    const timer = setTimeout(() => done(new Error('代理 CONNECT 超时')), timeoutMs || 20000);
    socket.once('close', () => done(new Error('代理连接已关闭')));
    socket.once('error', (e) => done(e));

    let head = '';
    const onData = (chunk) => {
      head += chunk.toString('latin1');
      const idx = head.indexOf('\r\n\r\n');
      if (idx === -1) {
        if (head.length > 16384) done(new Error('代理响应头过大'));
        return;
      }
      const firstLine = head.split('\r\n')[0] || '';
      const status = Number((firstLine.match(/^HTTP\/\d(?:\.\d)?\s+(\d+)/) || [])[1]);
      if (status !== 200) {
        return done(new Error('代理拒绝 CONNECT：' + (firstLine || 'unknown')));
      }
      const rest = Buffer.from(head.slice(idx + 4), 'latin1');
      if (rest.length) socket.unshift(rest);
      clearTimeout(timer);
      done(null);
    };

    let request =
      `CONNECT ${host}:${port} HTTP/1.1\r\n` +
      `Host: ${host}:${port}\r\n` +
      `Proxy-Connection: keep-alive\r\n`;
    if (proxy.username) {
      const auth = Buffer.from(`${proxy.username}:${proxy.password}`).toString('base64');
      request += `Proxy-Authorization: Basic ${auth}\r\n`;
    }
    request += '\r\n';
    socket.on('data', onData);
    socket.write(request);
  });
}

function socks5Connect(proxy, host, port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host: proxy.host, port: proxy.port });
    let stage = 'greeting';
    let settled = false;
    const done = (err) => {
      if (settled) return;
      settled = true;
      socket.removeAllListeners('data');
      socket.setTimeout(0);
      if (err) {
        socket.destroy();
        reject(err);
      } else {
        resolve(socket);
      }
    };
    socket.setTimeout(timeoutMs || 20000, () => done(new Error('SOCKS5 连接超时')));
    socket.once('error', (e) => done(e));
    socket.once('connect', () => {
      const methods = proxy.username ? [0x00, 0x02] : [0x00];
      socket.write(Buffer.from([0x05, methods.length, ...methods]));
    });

    let buffer = Buffer.alloc(0);
    socket.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (stage === 'greeting') {
        if (buffer.length < 2) return;
        const ver = buffer[0];
        const method = buffer[1];
        buffer = buffer.slice(2);
        if (ver !== 0x05) return done(new Error('SOCKS5 版本不匹配'));
        if (method === 0x02) {
          if (!proxy.username) return done(new Error('SOCKS5 代理要求用户名密码'));
          const u = Buffer.from(proxy.username);
          const p = Buffer.from(proxy.password);
          const auth = Buffer.concat([Buffer.from([0x01, u.length]), u, Buffer.from([p.length]), p]);
          socket.write(auth);
          stage = 'auth';
          return;
        }
        if (method !== 0x00) return done(new Error('SOCKS5 代理不接受当前认证方式'));
        stage = 'connect';
        return sendConnect();
      }
      if (stage === 'auth') {
        if (buffer.length < 2) return;
        const status = buffer[1];
        buffer = buffer.slice(2);
        if (status !== 0x00) return done(new Error('SOCKS5 认证失败'));
        stage = 'connect';
        return sendConnect();
      }
      if (stage === 'reply') {
        if (buffer.length < 4) return;
        const rep = buffer[1];
        const atyp = buffer[3];
        let need = 4;
        if (atyp === 0x01) need += 4;
        else if (atyp === 0x04) need += 16;
        else if (atyp === 0x03) {
          if (buffer.length < 5) return;
          need += 1 + buffer[4];
        }
        need += 2;
        if (buffer.length < need) return;
        if (rep !== 0x00) {
          const codes = {
            1: '通用失败', 2: '规则不允许', 3: '网络不可达', 4: '主机不可达',
            5: '连接被拒绝', 6: 'TTL 过期', 7: '命令不支持', 8: '地址类型不支持',
          };
          return done(new Error('SOCKS5 连接失败：' + (codes[rep] || rep)));
        }
        const rest = buffer.slice(need);
        if (rest.length) socket.unshift(rest);
        return done(null);
      }
    });

    async function sendConnect() {
      let atyp;
      let addr;
      if (proxy.protocol === 'socks5h:') {
        atyp = 0x03;
        addr = Buffer.from(host);
        const req = Buffer.concat([
          Buffer.from([0x05, 0x01, 0x00, atyp, addr.length]),
          addr,
          Buffer.from([(port >> 8) & 0xff, port & 0xff]),
        ]);
        stage = 'reply';
        socket.write(req);
        return;
      }
      try {
        const resolved = await dns.promises.lookup(host, { family: 4 });
        atyp = 0x01;
        const parts = resolved.address.split('.').map(Number);
        const req = Buffer.from([0x05, 0x01, 0x00, atyp, ...parts, (port >> 8) & 0xff, port & 0xff]);
        stage = 'reply';
        socket.write(req);
      } catch (e) {
        done(new Error('本地解析目标域名失败：' + host));
      }
    }
  });
}

async function tunnel(proxy, host, port, timeoutMs) {
  if (proxy.protocol === 'socks5:' || proxy.protocol === 'socks5h:') {
    return socks5Connect(proxy, host, port, timeoutMs);
  }
  return httpConnect(proxy, host, port, timeoutMs);
}

class ProxyAgent extends https.Agent {
  constructor(proxy, options = {}) {
    super({ keepAlive: true, maxSockets: 64, ...options });
    this.proxy = proxy;
    this.timeoutMs = options.timeoutMs || 20000;
  }

  createConnection(options, callback) {
    let called = false;
    const done = (err, socket) => {
      if (called) return;
      called = true;
      callback(err, socket);
    };
    tunnel(this.proxy, options.host, options.port, this.timeoutMs)
      .then((raw) => {
        const secured = tls.connect({
          socket: raw,
          servername: options.servername || options.host,
          ALPNProtocols: ['http/1.1'],
        });
        secured.once('secureConnect', () => done(null, secured));
        secured.once('error', (err) => done(err));
      })
      .catch((err) => done(err));
  }
}

function agentFor(proxyRaw) {
  if (!proxyRaw) return null;
  const proxy = typeof proxyRaw === 'string' ? parseProxy(proxyRaw) : proxyRaw;
  if (!proxy) return null;
  const key = proxy.raw || `${proxy.protocol}//${proxy.host}:${proxy.port}`;
  let agent = agentCache.get(key);
  if (!agent) {
    agent = new ProxyAgent(proxy, { timeoutMs: 20000 });
    agentCache.set(key, agent);
  }
  return agent;
}

function clearAgentCache() {
  for (const agent of agentCache.values()) {
    try {
      agent.destroy();
    } catch {}
  }
  agentCache.clear();
}

module.exports = { agentFor, clearAgentCache, tunnel, ProxyAgent };
