'use strict';
// Runs the conversion engine as a child process (never on the UI thread, never
// through a shell). Packaged builds use the bundled executable; development runs
// use Python with the engine package in ../../engine.

const { spawn } = require('child_process');
const path = require('path');
const readline = require('readline');

/**
 * Resolve how to start the engine.
 * @param {{isPackaged: boolean, resourcesPath: string, platform: string, env: object, engineDir: string}} opts
 * @returns {{command: string, args: string[], cwd?: string, env: object}}
 */
function resolveEngine(opts) {
  const { isPackaged, resourcesPath, platform, env, engineDir } = opts;
  const exeName = platform === 'win32' ? 'dgm-engine.exe' : 'dgm-engine';
  if (env.DGM_ENGINE_EXE) {
    return { command: env.DGM_ENGINE_EXE, args: [], env: {} };
  }
  if (isPackaged) {
    return {
      command: path.join(resourcesPath, 'engine', exeName),
      args: [],
      env: {},
    };
  }
  const python = env.DGM_PYTHON || (platform === 'win32' ? 'python' : 'python3');
  return {
    command: python,
    args: ['-m', 'dgm_engine'],
    cwd: engineDir,
    env: { PYTHONPATH: engineDir, PYTHONIOENCODING: 'utf-8' },
  };
}

/** Parse one JSON event line from the engine. Returns null for anything else. */
function parseEventLine(line) {
  const text = String(line).trim();
  if (!text.startsWith('{')) return null;
  try {
    const obj = JSON.parse(text);
    return obj && typeof obj === 'object' && typeof obj.event === 'string' ? obj : null;
  } catch (_e) {
    return null;
  }
}

function spawnEngine(resolved, args, { onEvent, onStderr } = {}) {
  const child = spawn(resolved.command, [...resolved.args, ...args], {
    cwd: resolved.cwd,
    env: { ...process.env, ...resolved.env },
    shell: false,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const rl = readline.createInterface({ input: child.stdout });
  rl.on('line', (line) => {
    const ev = parseEventLine(line);
    if (ev && onEvent) onEvent(ev);
  });
  let stderrTail = '';
  child.stderr.on('data', (chunk) => {
    stderrTail = (stderrTail + chunk.toString('utf8')).slice(-4000);
    if (onStderr) onStderr(chunk.toString('utf8'));
  });
  child.stderrTail = () => stderrTail;
  return child;
}

/**
 * Run `inspect` and resolve with the parsed JSON document.
 * Rejects on engine failure (not on rejected tiles, which are returned in `errors`).
 */
function runInspect(resolved, tiles, bbox) {
  // Options must come before '--'; everything after it is a file path.
  const args = ['inspect'];
  if (bbox) args.push('--bbox', ...bbox.map((n) => String(n)));
  args.push('--', ...tiles);
  return new Promise((resolve, reject) => {
    let out = '';
    const child = spawn(resolved.command, [...resolved.args, ...args], {
      cwd: resolved.cwd,
      env: { ...process.env, ...resolved.env },
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let err = '';
    child.stdout.on('data', (c) => { out += c.toString('utf8'); });
    child.stderr.on('data', (c) => { err = (err + c.toString('utf8')).slice(-2000); });
    child.on('error', (e) => reject(new Error(`Cannot start the engine: ${e.message}`)));
    child.on('close', (code) => {
      if (code !== 0 && !out.trim()) {
        reject(new Error(`Engine failed (exit ${code}). ${err.trim().split('\n').pop() || ''}`.trim()));
        return;
      }
      try {
        resolve(JSON.parse(out.trim().split('\n').filter(Boolean).pop()));
      } catch (_e) {
        reject(new Error('The engine returned unreadable output.'));
      }
    });
  });
}

module.exports = { resolveEngine, parseEventLine, spawnEngine, runInspect };
