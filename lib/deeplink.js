'use strict';

/**
 * irisgo:// 协议处理器。
 * Windows 会把完整 URL 作为第一个参数传进来，这里把它转交给本地服务。
 * 如果服务没在运行，就写入队列，等下次启动时处理。
 */

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

const ROOT = path.dirname(__dirname);
const DATA = path.join(ROOT, 'data');
const url = process.argv[2] || '';

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function readText(file) {
  try {
    return fs.readFileSync(file, 'utf8').trim();
  } catch {
    return '';
  }
}

function queue() {
  try {
    fs.mkdirSync(DATA, { recursive: true });
    fs.appendFileSync(path.join(DATA, 'deeplink-queue.jsonl'), JSON.stringify({ url, at: Date.now() }) + '\n', 'utf8');
  } catch {}
}

function main() {
  if (!url) process.exit(0);
  const config = readJson(path.join(DATA, 'config.json'), {});
  const port = Number(config?.server?.port) || 8787;
  const secret = readText(path.join(DATA, 'deeplink-secret.txt'));
  const body = JSON.stringify({ url, secret });

  const req = http.request(
    {
      host: '127.0.0.1',
      port,
      path: '/api/oauth/deeplink',
      method: 'POST',
      timeout: 4000,
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    },
    (res) => {
      res.resume();
      res.on('end', () => process.exit(0));
    }
  );
  req.on('timeout', () => {
    req.destroy();
    queue();
    process.exit(0);
  });
  req.on('error', () => {
    queue();
    process.exit(0);
  });
  req.end(body);
}

main();
