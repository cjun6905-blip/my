'use strict';

const fs = require('node:fs');
const path = require('node:path');
const https = require('node:https');
const { agentFor } = require('./proxies');

const OR_URL = 'https://openrouter.ai/api/v1/models';
const CACHE_TTL_MS = 6 * 3600 * 1000;

const FALLBACK = [
  { id: 'google/gemini-3.8-flash', name: 'Gemini 3.8 Flash', context_length: 1000000, pricing: { prompt: 0.00000015, completion: 0.0000006 } },
  { id: 'openai/gpt-6-luna', name: 'GPT-6 Luna', context_length: 400000, pricing: { prompt: 0.000001, completion: 0.000004 } },
];

let memoryCache = null;

function cachePath(dataDir) {
  return path.join(dataDir, 'models-cache.json');
}

function loadDiskCache(dataDir) {
  try {
    const raw = JSON.parse(fs.readFileSync(cachePath(dataDir), 'utf8'));
    if (Array.isArray(raw.models) && raw.models.length) return raw;
  } catch {}
  return null;
}

function saveDiskCache(dataDir, payload) {
  try {
    fs.writeFileSync(cachePath(dataDir), JSON.stringify(payload), 'utf8');
  } catch {}
}

function httpGetJson(url, proxy, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const agent = agentFor(proxy);
    const req = https.request(
      {
        host: u.hostname,
        port: 443,
        path: u.pathname + u.search,
        method: 'GET',
        agent: agent || undefined,
        servername: u.hostname,
        headers: { Accept: 'application/json', 'User-Agent': 'IrisGoProxy/1.0' },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          if (res.statusCode !== 200) return reject(new Error('OpenRouter 返回 HTTP ' + res.statusCode));
          try {
            resolve(JSON.parse(text));
          } catch (e) {
            reject(new Error('OpenRouter 返回的不是 JSON'));
          }
        });
        res.on('error', reject);
      }
    );
    req.setTimeout(timeoutMs, () => req.destroy(new Error('获取模型目录超时')));
    req.on('error', reject);
    req.end();
  });
}

function normalize(raw) {
  return {
    id: String(raw.id || ''),
    name: String(raw.name || raw.id || ''),
    context_length: Number(raw.context_length || raw.top_provider?.context_length || 0) || 0,
    pricing: {
      prompt: Number(raw.pricing?.prompt || 0) || 0,
      completion: Number(raw.pricing?.completion || 0) || 0,
    },
    created: Number(raw.created || 0) || 0,
  };
}

async function fetchCatalog({ dataDir, proxy, force = false }) {
  const now = Date.now();
  if (!force && memoryCache && now - memoryCache.fetchedAt < CACHE_TTL_MS) return memoryCache;

  if (!force) {
    const disk = loadDiskCache(dataDir);
    if (disk && now - Number(disk.fetchedAt || 0) < CACHE_TTL_MS) {
      memoryCache = { fetchedAt: Number(disk.fetchedAt), models: disk.models, source: 'cache' };
      return memoryCache;
    }
  }

  try {
    const data = await httpGetJson(OR_URL, proxy);
    const models = (data?.data || []).map(normalize).filter((m) => m.id);
    if (!models.length) throw new Error('模型目录为空');
    memoryCache = { fetchedAt: now, models, source: 'openrouter' };
    saveDiskCache(dataDir, { fetchedAt: now, models });
    return memoryCache;
  } catch (err) {
    const disk = loadDiskCache(dataDir);
    if (disk && disk.models?.length) {
      memoryCache = { fetchedAt: Number(disk.fetchedAt) || 0, models: disk.models, source: 'stale', error: err.message };
      return memoryCache;
    }
    memoryCache = { fetchedAt: now, models: FALLBACK, source: 'fallback', error: err.message };
    return memoryCache;
  }
}

function visibleModels(catalog, config) {
  const hidden = new Set((config.hidden || []).map(String));
  const only = Array.isArray(config.only) && config.only.length ? new Set(config.only.map(String)) : null;
  const list = catalog.models.filter((m) => !hidden.has(m.id) && (!only || only.has(m.id)));
  const out = [];
  if (config.includeAuto !== false) {
    out.push({
      id: 'auto',
      name: 'Auto（IrisGo 自动路由）',
      context_length: 0,
      pricing: { prompt: 0, completion: 0 },
      created: 0,
    });
  }
  out.push(...list);
  return out;
}

function toOpenAiShape(models) {
  const now = Math.floor(Date.now() / 1000);
  return {
    object: 'list',
    data: models.map((m) => ({
      id: m.id,
      object: 'model',
      created: m.created || now,
      owned_by: m.id.includes('/') ? m.id.split('/')[0] : 'irisgo',
      name: m.name,
      context_length: m.context_length,
      pricing: m.pricing,
    })),
  };
}

function clearMemoryCache() {
  memoryCache = null;
}

module.exports = { fetchCatalog, visibleModels, toOpenAiShape, clearMemoryCache, FALLBACK };
