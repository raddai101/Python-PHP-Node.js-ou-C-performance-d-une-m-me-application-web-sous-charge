'use strict';
// Mini-Task API — version JavaScript natif (Node.js 22, module `http`, sans
// framework), port 8082.   Lancement : node server.js

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const PORT = 8082;
const HOST = '127.0.0.1';
const MAX_N = 40;
const MAX_BODY = 1024 * 1024;
const CONTENT_TYPE = 'application/json; charset=utf-8';

// --- Données en mémoire -------------------------------------------------------
const tasks = JSON.parse(fs.readFileSync(path.join(__dirname, 'tasks.json'), 'utf8'));
const byId = new Map(tasks.map((t) => [t.id, t]));
let nextId = tasks.length + 1;

const utf8 = new TextDecoder('utf-8', { fatal: true });

function fib(n) {
  return n < 2 ? n : fib(n - 1) + fib(n - 2);
}

function send(res, status, body) {
  const buf = Buffer.from(JSON.stringify(body), 'utf8');
  res.writeHead(status, { 'Content-Type': CONTENT_TYPE, 'Content-Length': buf.length });
  res.end(buf);
}

const notFound = (res) => send(res, 404, { error: 'not found' });
const badPayload = (res) => send(res, 400, { error: 'invalid payload' });

function handleCreate(req, res) {
  const chunks = [];
  let size = 0;
  let aborted = false;
  req.on('data', (chunk) => {
    size += chunk.length;
    if (size > MAX_BODY) {
      aborted = true;
      badPayload(res);
      req.destroy();
      return;
    }
    chunks.push(chunk);
  });
  req.on('end', () => {
    if (aborted) return;
    let payload;
    try {
      payload = JSON.parse(utf8.decode(Buffer.concat(chunks)));
    } catch {
      return badPayload(res);
    }
    if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
      return badPayload(res);
    }
    const { title, priority } = payload;
    const done = 'done' in payload ? payload.done : false;
    if (
      typeof title !== 'string' || title === '' ||
      !Number.isInteger(priority) || priority < 1 || priority > 5 ||
      typeof done !== 'boolean'
    ) {
      return badPayload(res);
    }
    const task = { id: nextId++, title, done, priority };
    tasks.push(task);
    byId.set(task.id, task);
    send(res, 201, task);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const { pathname } = url;
  const method = req.method;

  if (method === 'GET' && pathname === '/health') return send(res, 200, { status: 'ok' });
  if (method === 'GET' && pathname === '/tasks') return send(res, 200, tasks);
  if (method === 'POST' && pathname === '/tasks') return handleCreate(req, res);

  if (method === 'GET' && pathname.startsWith('/tasks/')) {
    const raw = pathname.slice('/tasks/'.length);
    if (/^[0-9]{1,18}$/.test(raw)) {
      const task = byId.get(Number(raw));
      if (task !== undefined) return send(res, 200, task);
    }
    return notFound(res);
  }

  if (method === 'GET' && pathname === '/compute') {
    const raw = url.searchParams.get('n');
    if (raw === null || !/^[0-9]{1,18}$/.test(raw) || Number(raw) > MAX_N) {
      return send(res, 400, { error: 'invalid n' });
    }
    const n = Number(raw);
    return send(res, 200, { n, result: fib(n) });
  }

  return notFound(res);
});

server.listen(PORT, HOST);
