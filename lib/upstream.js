'use strict';

const https = require('node:https');
const { agentFor } = require('./proxies');

const API_HOST = 'api.irisgo.ai';

const PATHS = {
  chat: '/v1/openrouter/chat/completions',
  responses: '/v1/openrouter/responses',
};

const PASS_HEADERS = [
  'content-type',
  'x-request-id',
  'x-upstream-request-id',
  'x-irisgo-resolved-model',
  'x-irisgo-routing-version',
  'x-irisgo-routing-reason',
  'retry-after',
  'x-should-retry',
];

function prepareBody(input) {
  const body = { ...input };
  let routingTarget = null;
  let model = typeof body.model === 'string' ? body.model.trim() : '';

  if (!model) model = 'auto';
  if (model === 'auto' || model === 'strategy:auto') {
    routingTarget = 'strategy:auto';
    model = 'auto';
  } else if (model.startsWith('strategy:')) {
    routingTarget = model;
    model = 'auto';
  }
  body.model = model;
  return { body, routingTarget };
}

function request(account, { method = 'POST', path: urlPath, body, stream = false, timeoutMs = 300000, extraHeaders = {} }) {
  return new Promise((resolve, reject) => {
    const prepared = body ? prepareBody(body) : { body: null, routingTarget: null };
    const payload = prepared.body ? Buffer.from(JSON.stringify(prepared.body)) : null;
    const agent = agentFor(account.proxy);
    const headers = {
      Authorization: 'Bearer ' + account.token,
      Accept: stream ? 'text/event-stream' : 'application/json',
      'User-Agent': 'IrisGoProxy/1.0',
      ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}),
      ...(prepared.routingTarget ? { 'x-irisgo-routing-target': prepared.routingTarget } : {}),
      ...extraHeaders,
    };

    const req = https.request(
      {
        host: API_HOST,
        port: 443,
        method,
        path: urlPath,
        agent: agent || undefined,
        servername: API_HOST,
        headers,
      },
      (res) => resolve(res)
    );

    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error('上游响应超时（' + Math.round(timeoutMs / 1000) + 's）'));
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function collect(res, limit = 64 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    res.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        res.destroy();
        reject(new Error('上游响应体过大'));
        return;
      }
      chunks.push(chunk);
    });
    res.on('end', () => resolve(Buffer.concat(chunks)));
    res.on('error', reject);
  });
}

function filterHeaders(upstreamHeaders) {
  const out = {};
  for (const name of PASS_HEADERS) {
    const value = upstreamHeaders[name];
    if (value !== undefined) out[name] = Array.isArray(value) ? value.join(', ') : value;
  }
  return out;
}

function parseUsage(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const usage = payload.usage;
  if (!usage || typeof usage !== 'object') return null;
  const input = Number(usage.input_tokens ?? usage.prompt_tokens ?? 0) || 0;
  const output = Number(usage.output_tokens ?? usage.completion_tokens ?? 0) || 0;
  if (!input && !output) return null;
  return { input, output };
}

module.exports = { API_HOST, PATHS, request, collect, filterHeaders, parseUsage, prepareBody };
