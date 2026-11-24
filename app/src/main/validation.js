'use strict';
// Input validation for values coming from the renderer. Everything the renderer
// sends is untrusted: paths, numbers and names are checked here before use.

const fs = require('fs');
const path = require('path');

const TILE_RE = /^dgm[_-].*\.tif(f)?$/i;
const DOM_RE = /^dom[_-]/i;
const PREFIX_RE = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_TILES = 2000;

function isSafeAbsolutePath(p) {
  return typeof p === 'string' && p.length > 0 && p.length < 4096 &&
    !p.includes('\0') && path.isAbsolute(p);
}

/** True when a path is a DGM elevation GeoTIFF that exists on disk. */
function validateTilePath(p) {
  if (!isSafeAbsolutePath(p)) return { ok: false, reason: 'not an absolute path' };
  const base = path.basename(p);
  if (DOM_RE.test(base)) {
    return { ok: false, reason: 'names starting with dom_ are DOM images, not elevation' };
  }
  if (!TILE_RE.test(base)) return { ok: false, reason: 'expected a dgm_*.tif file' };
  let st;
  try {
    st = fs.statSync(p);
  } catch (_e) {
    return { ok: false, reason: 'file not found' };
  }
  if (!st.isFile()) return { ok: false, reason: 'not a file' };
  return { ok: true };
}

/** Lists dgm_*.tif files directly inside a folder (not recursive). */
function listTilesInFolder(dir) {
  if (!isSafeAbsolutePath(dir)) throw new Error('Invalid folder path.');
  const names = fs.readdirSync(dir, { withFileTypes: true });
  const out = [];
  for (const d of names) {
    if (!d.isFile()) continue;
    if (DOM_RE.test(d.name)) continue;
    if (!TILE_RE.test(d.name)) continue;
    out.push(path.join(dir, d.name));
    if (out.length >= MAX_TILES) break;
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function validateTileList(list) {
  if (!Array.isArray(list) || list.length === 0) throw new Error('No tiles selected.');
  if (list.length > MAX_TILES) throw new Error(`Too many tiles (limit ${MAX_TILES}).`);
  const out = [];
  for (const p of list) {
    const v = validateTilePath(p);
    if (!v.ok) throw new Error(`${path.basename(String(p))}: ${v.reason}.`);
    out.push(p);
  }
  return out;
}

/** Returns null (no box) or [xmin, ymin, xmax, ymax] with finite numbers. */
function validateBbox(bbox) {
  if (bbox === null || bbox === undefined) return null;
  if (!Array.isArray(bbox) || bbox.length !== 4) throw new Error('The bounding box needs four numbers.');
  const v = bbox.map((n) => (typeof n === 'number' ? n : Number(n)));
  if (!v.every((n) => Number.isFinite(n))) throw new Error('The bounding box must contain numbers.');
  if (!(v[0] < v[2] && v[1] < v[3])) throw new Error('The bounding box needs xmin < xmax and ymin < ymax.');
  if (v.some((n) => Math.abs(n) > 1e9)) throw new Error('Bounding box values are out of range.');
  return v;
}

function validatePrefix(prefix) {
  if (typeof prefix !== 'string' || !PREFIX_RE.test(prefix)) {
    throw new Error('The file prefix may only contain letters, digits, _ and -.');
  }
  return prefix;
}

function validateOutputDir(dir) {
  if (!isSafeAbsolutePath(dir)) throw new Error('Choose an output folder.');
  let st;
  try {
    st = fs.statSync(dir);
  } catch (_e) {
    throw new Error('The output folder does not exist.');
  }
  if (!st.isDirectory()) throw new Error('The output location is not a folder.');
  return dir;
}

/** True when child is inside parent (or equal to it). */
function isInside(parent, child) {
  const rel = path.relative(path.resolve(parent), path.resolve(child));
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/** Job folders created by the engine are hidden, named .dgm-job-<id>. */
function isJobDirName(name) {
  return /^\.dgm-job-[a-f0-9]{10}$/.test(name);
}

module.exports = {
  validateTilePath,
  listTilesInFolder,
  validateTileList,
  validateBbox,
  validatePrefix,
  validateOutputDir,
  isInside,
  isJobDirName,
  isSafeAbsolutePath,
  MAX_TILES,
};
