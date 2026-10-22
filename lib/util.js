'use strict';

const crypto = require('node:crypto');

function uid(bytes = 8) {
  return crypto.randomBytes(bytes).toString('hex');
}

function nowSec() {
  return Math.floor(Date.now() / 1000);
}

function sha256(input) {
  return crypto.createHash('sha256').update(String(input)).digest('hex');
}

function hmac(secret, input) {
  return crypto.createHmac('sha256', String(secret)).update(String(input)).digest('base64url');
}

function safeEqual(a, b) {
  const ab = Buffer.from(String(a ?? ''));
  const bb = Buffer.from(String(b ?? ''));
  if (ab.length !== bb.length) return false;
  return crypto.timingSafeEqual(ab, bb);
}

function b64urlDecode(input) {
  const s = String(input).replace(/-/g, '+').replace(/_/g, '/');
  return Buffer.from(s, 'base64');
}

function b64urlJson(input) {
  try {
    return JSON.parse(b64urlDecode(input).toString('utf8'));
  } catch {
    return null;
  }
}

function maskToken(token) {
  if (!token) return '';
  if (token.length <= 18) return token.slice(0, 4) + '***';
  return token.slice(0, 10) + '…' + token.slice(-6);
}

function json(res, status, obj, extraHeaders = {}) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  res.end(body);
}

function sendError(res, status, message, type = 'invalid_request_error', code = null) {
  json(res, status, { error: { message, type, code, param: null } });
}

function readBody(req, limit = 32 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(Object.assign(new Error('request body too large'), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

async function readJson(req, limit) {
  const buf = await readBody(req, limit);
  if (!buf.length) return {};
  try {
    return JSON.parse(buf.toString('utf8'));
  } catch {
    throw Object.assign(new Error('invalid JSON body'), { statusCode: 400 });
  }
}

function parseCookies(req) {
  const header = req.headers.cookie || '';
  const out = {};
  for (const part of header.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

function parseProxy(raw) {
  if (!raw) return null;
  let s = String(raw).trim();
  if (!s) return null;
  if (!/^[a-z0-9+.-]+:\/\//i.test(s)) s = 'http://' + s;
  let u;
  try {
    u = new URL(s);
  } catch {
    throw new Error('代理地址格式不正确：' + raw);
  }
  const protocol = u.protocol.toLowerCase();
  if (!['http:', 'https:', 'socks5:', 'socks5h:'].includes(protocol)) {
    throw new Error('不支持的代理协议：' + protocol);
  }
  const defaultPort = protocol.startsWith('socks') ? 1080 : 8080;
  return {
    protocol,
    host: u.hostname,
    port: Number(u.port || defaultPort),
    username: decodeURIComponent(u.username || ''),
    password: decodeURIComponent(u.password || ''),
    raw: s,
  };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

function createLogger(file) {
  const fs = require('node:fs');
  const path = require('node:path');
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
  } catch {}
  const stream = fs.createWriteStream(file, { flags: 'a' });
  const write = (level, args) => {
    const line = `[${new Date().toISOString()}] [${level}] ${args
      .map((a) => (typeof a === 'string' ? a : safeStringify(a)))
      .join(' ')}`;
    stream.write(line + '\n');
    if (level === 'ERROR') console.error(line);
    else console.log(line);
  };
  return {
    info: (...a) => write('INFO', a),
    warn: (...a) => write('WARN', a),
    error: (...a) => write('ERROR', a),
  };
}

function safeStringify(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

module.exports = {
  uid,
  nowSec,
  sha256,
  hmac,
  safeEqual,
  b64urlDecode,
  b64urlJson,
  maskToken,
  json,
  sendError,
  readBody,
  readJson,
  parseCookies,
  parseProxy,
  sleep,
  clamp,
  createLogger,
  safeStringify,
};
