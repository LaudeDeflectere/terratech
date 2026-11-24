'use strict';
// Renderer: UI only. All file access, processing and validation happen in the
// main process and the engine. Untrusted strings (file names, messages) are
// always inserted with textContent, never as HTML.

(() => {
  const $ = (id) => document.getElementById(id);
  const api = window.dgm;

  const state = {
    tilePaths: [],     // accepted and pending paths, in order
    inspect: null,     // last inspect result
    coverage: null,    // coverage result for the current box
    outputDir: null,
    running: false,
    lastOutputs: [],
  };

  // ------------------------------------------------------------ helpers

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else n.setAttribute(k, v === true ? '' : String(v));
      }
    }
    for (const c of children) {
      if (c === null || c === undefined) continue;
      n.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }

  function fmtBytes(b) {
    if (b === null || b === undefined) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let v = Number(b);
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function fmtNum(n) {
    return Number(n || 0).toLocaleString('en-US');
  }

  function setStatus(id, kind, message) {
    const box = $(id);
    box.replaceChildren();
    box.className = `status ${kind || ''}`;
    if (message) box.append(message instanceof Node ? message : document.createTextNode(message));
  }

  function basename(p) {
    return String(p).split(/[\\/]/).pop();
  }

  function parseNum(input) {
    const v = input.value.trim();
    if (v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  }

  // ------------------------------------------------------------ tiles

  async function addPaths(paths) {
    if (state.running) return;
    const filtered = await api.filterTiles(paths);
    const rejected = paths.filter((p) => !filtered.includes(p));
    for (const p of filtered) if (!state.tilePaths.includes(p)) state.tilePaths.push(p);
    await refreshInspect();
    if (rejected.length) {
      const msg = `${rejected.length} file(s) were not accepted (only dgm_*.tif elevation files): ` +
        rejected.map(basename).join(', ');
      setStatus('tile-status', 'warn', msg);
    }
  }

  async function refreshInspect() {
    if (state.tilePaths.length === 0) {
      state.inspect = null;
      state.coverage = null;
      $('tile-table').hidden = true;
      $('coverage-box').hidden = true;
      setStatus('tile-status', '', 'No tiles loaded yet.');
      updateStartState();
      return;
    }
    setStatus('tile-status', 'busy', `Checking ${state.tilePaths.length} tile(s)…`);
    try {
      const bbox = currentBbox();
      const res = await api.inspect(state.tilePaths, bbox);
      state.inspect = res;
      state.coverage = res.coverage || null;
      renderTiles(res);
      renderCoverage(res);
      renderCoverageStatus(res);
    } catch (err) {
      setStatus('tile-status', 'error', `Could not check the tiles: ${err.message}`);
    }
    updateStartState();
  }

  function renderTiles(res) {
    const tbody = document.querySelector('#tile-table tbody');
    tbody.replaceChildren();
    const ok = res.tiles || [];
    const bad = res.errors || [];
    for (const t of ok) {
      tbody.append(el('tr', {},
        el('td', { class: 'mono' }, t.name),
        el('td', { class: 'ok' }, 'accepted'),
        el('td', {}, t.epsg ? `EPSG:${t.epsg}` : ''),
        el('td', {}, `${t.res} m`),
        el('td', {}, `${fmtNum(t.width)} × ${fmtNum(t.height)}`),
        el('td', { class: 'mono small' },
          `x ${t.left.toFixed(1)} … ${t.right.toFixed(1)}, y ${t.bottom.toFixed(1)} … ${t.top.toFixed(1)}`),
        el('td', {}, `${t.elev_min.toFixed(2)} … ${t.elev_max.toFixed(2)}`),
      ));
      for (const w of t.warnings || []) {
        tbody.append(el('tr', { class: 'warnrow' }, el('td', { colspan: '7' }, `${t.name}: ${w}`)));
      }
    }
    for (const e of bad) {
      tbody.append(el('tr', { class: 'badrow' },
        el('td', { class: 'mono' }, e.file),
        el('td', { colspan: '6', class: 'bad' }, `rejected: ${e.message}`),
      ));
    }
    $('tile-table').hidden = (ok.length + bad.length) === 0;

    const parts = [];
    if (ok.length) parts.push(`${ok.length} tile(s) accepted`);
    if (bad.length) parts.push(`${bad.length} rejected`);
    if (ok.length) {
      parts.push(`elevation ${res.elev_min.toFixed(2)} … ${res.elev_max.toFixed(2)} m`);
      parts.push(`cell size ${res.res} m`);
    }
    setStatus('tile-status', bad.length && !ok.length ? 'error' : (bad.length ? 'warn' : 'ok'),
      parts.join(' · ') || 'No accepted tiles.');
  }

  function renderCoverage(res) {
    const svg = $('coverage-map');
    svg.replaceChildren();
    const u = res.union;
    if (!u) { $('coverage-box').hidden = true; return; }
    $('coverage-box').hidden = false;

    const bbox = currentBbox();
    let minX = u.left, maxX = u.right, minY = u.bottom, maxY = u.top;
    if (bbox) {
      minX = Math.min(minX, bbox[0]); minY = Math.min(minY, bbox[1]);
      maxX = Math.max(maxX, bbox[2]); maxY = Math.max(maxY, bbox[3]);
    }
    const W = 600, H = 360, pad = 16;
    const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
    const scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
    const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
    const X = (x) => ox + (x - minX) * scale;
    const Y = (y) => oy + (maxY - y) * scale;
    const NS = 'http://www.w3.org/2000/svg';
    const sv = (tag, attrs) => {
      const n = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
      return n;
    };
    svg.append(sv('rect', { x: 0, y: 0, width: W, height: H, fill: '#ffffff' }));
    for (const t of res.tiles || []) {
      svg.append(sv('rect', {
        x: X(t.left), y: Y(t.top), width: (t.right - t.left) * scale, height: (t.top - t.bottom) * scale,
        fill: '#3b82f6', 'fill-opacity': '0.25', stroke: '#1d4ed8', 'stroke-width': '1',
      }));
    }
    if (bbox) {
      svg.append(sv('rect', {
        x: X(bbox[0]), y: Y(bbox[3]), width: (bbox[2] - bbox[0]) * scale, height: (bbox[3] - bbox[1]) * scale,
        fill: 'none', stroke: '#dc2626', 'stroke-width': '2', 'stroke-dasharray': '6 4',
      }));
    }
    const label = bbox
      ? `Requested area; tiles cover ${(100 * ((state.coverage && state.coverage.fraction) || 0)).toFixed(1)} %`
      : 'Full extent of the selected tiles';
    svg.append(sv('text', { x: 12, y: H - 10, 'font-size': '13', fill: '#334155' }));
    svg.lastChild.textContent = label;
  }

  function renderCoverageStatus(res) {
    if (!currentBbox()) {
      setStatus('coverage-status', '', 'Full extent of the selected tiles will be processed.');
      return;
    }
    if (res.coverage_error) {
      setStatus('coverage-status', 'error', res.coverage_error);
      return;
    }
    if (!res.coverage) {
      setStatus('coverage-status', '', 'Press “Check coverage” to test the requested area.');
      return;
    }
    const pct = 100 * res.coverage.fraction;
    const missing = res.coverage.requested_cells - res.coverage.covered_cells;
    if (missing > 0) {
      setStatus('coverage-status', 'warn',
        `The tiles do NOT completely cover the requested area: ${pct.toFixed(2)} % of its ` +
        `${fmtNum(res.coverage.requested_cells)} cell centres have DGM data. ` +
        `${fmtNum(missing)} cell centres will be left out.`);
    } else {
      setStatus('coverage-status', 'ok',
        `The tiles completely cover the requested area (${fmtNum(res.coverage.requested_cells)} cell centres).`);
    }
  }

  // ------------------------------------------------------------ bbox

  function currentBbox() {
    if (!$('use-bbox').checked) return null;
    const vals = ['bb-xmin', 'bb-ymin', 'bb-xmax', 'bb-ymax'].map((id) => parseNum($(id)));
    if (vals.some((v) => v === null || Number.isNaN(v))) return null;
    if (!(vals[0] < vals[2] && vals[1] < vals[3])) return null;
    return vals;
  }

  function bboxProblem() {
    if (!$('use-bbox').checked) return null;
    const vals = ['bb-xmin', 'bb-ymin', 'bb-xmax', 'bb-ymax'].map((id) => parseNum($(id)));
    if (vals.some((v) => v === null)) return 'Enter all four bounding-box values.';
    if (vals.some((v) => Number.isNaN(v))) return 'Bounding-box values must be numbers.';
    if (!(vals[0] < vals[2] && vals[1] < vals[3])) return 'Use xmin < xmax and ymin < ymax.';
    return null;
  }

  function intervalProblem() {
    const i = parseNum($('interval'));
    const m = parseNum($('major'));
    if (i === null || m === null || Number.isNaN(i) || Number.isNaN(m) || i <= 0 || m <= 0) {
      return 'Contour intervals must be positive numbers.';
    }
    const ratio = m / i;
    if (Math.abs(ratio - Math.round(ratio)) > 1e-9 || Math.round(ratio) < 1) {
      return 'The major interval must be a whole multiple of the contour interval (e.g. 1 and 5).';
    }
    return null;
  }

  function updateHints() {
    const p = intervalProblem();
    const hint = $('interval-hint');
    hint.textContent = p || `Major contours every ${$('major').value} m (${Math.round(parseNum($('major')) / parseNum($('interval')))} contour steps).`;
    hint.className = p ? 'hint bad' : 'hint';
    for (const id of ['bb-xmin', 'bb-ymin', 'bb-xmax', 'bb-ymax']) $(id).disabled = !$('use-bbox').checked;
    $('btn-check-cover').disabled = !$('use-bbox').checked || state.tilePaths.length === 0 || bboxProblem() !== null;
    updateStartState();
  }

  function updateStartState() {
    const outputs = selectedOutputs();
    const problems = [];
    if (state.tilePaths.length === 0) problems.push('add tiles');
    if (!state.inspect || !(state.inspect.tiles || []).length) problems.push('at least one accepted tile');
    if (outputs.length === 0) problems.push('select an output');
    if (!state.outputDir) problems.push('choose an output folder');
    if (intervalProblem()) problems.push('fix the contour intervals');
    if (bboxProblem()) problems.push('fix the bounding box');
    $('btn-start').disabled = state.running || problems.length > 0;
    $('btn-start').title = problems.length ? `To start: ${problems.join(', ')}` : '';
    $('btn-cancel').disabled = !state.running;
    $('btn-pick-files').disabled = state.running;
    $('btn-pick-folder').disabled = state.running;
    $('btn-clear').disabled = state.running;
    $('btn-pick-output').disabled = state.running;
  }

  function selectedOutputs() {
    const out = [];
    if ($('out-contours').checked) out.push('contours');
    if ($('out-points').checked) out.push('points');
    if ($('out-tin').checked) out.push('tin');
    return out;
  }

  // ------------------------------------------------------------ run

  function appendLog(text, kind) {
    const li = el('li', { class: kind || '' }, `${new Date().toLocaleTimeString()}  ${text}`);
    $('log').append(li);
    li.scrollIntoView({ block: 'nearest' });
  }

  function setRunning(on) {
    state.running = on;
    $('progress').hidden = !on;
    updateStartState();
  }

  function onJobEvent(ev) {
    switch (ev.event) {
      case 'progress': {
        $('bar-fill').style.width = `${Math.round(ev.fraction * 100)}%`;
        $('progress-text').textContent = `${ev.message} (${Math.round(ev.fraction * 100)} %)`;
        break;
      }
      case 'warning':
        appendLog(ev.message, 'warn');
        break;
      case 'job':
        appendLog('Working in a temporary job folder inside the output folder.');
        break;
      case 'done':
        finishSuccess(ev);
        break;
      case 'cancelled':
        setRunning(false);
        setStatus('run-status', 'warn', ev.message);
        appendLog(ev.message, 'warn');
        break;
      case 'error':
        setRunning(false);
        setStatus('run-status', 'error', ev.message);
        appendLog(ev.message, 'bad');
        break;
      default:
        break;
    }
  }

  function finishSuccess(ev) {
    setRunning(false);
    $('progress-text').textContent = 'Finished.';
    $('bar-fill').style.width = '100%';
    setStatus('run-status', 'ok', 'Conversion finished. Files are in the output folder.');
    appendLog('Finished.', 'ok');
    const tbody = document.querySelector('#result-table tbody');
    tbody.replaceChildren();
    const rows = [...ev.outputs.map((o) => ({ name: o.file, bytes: o.bytes, counts: o.counts }))];
    rows.push({ name: basename(ev.readme), bytes: null, counts: null });
    if (ev.zip) rows.push({ name: basename(ev.zip), bytes: ev.zip_bytes, counts: null });
    for (const r of rows) {
      tbody.append(el('tr', {},
        el('td', { class: 'mono' }, r.name),
        el('td', {}, fmtBytes(r.bytes)),
        el('td', {}, describeCounts(r.counts))));
    }
    $('result-note').textContent =
      `Coverage of the requested area: ${(100 * ev.coverage_fraction).toFixed(2)} %. ` +
      `Elevation of the cells used: ${ev.elevation_min.toFixed(2)} … ${ev.elevation_max.toFixed(2)} m. ` +
      'AutoCAD DXF does not reliably store the coordinate system: assign EPSG:31258 in Civil 3D (see the README).';
    state.lastOutputs = ev.outputs;
    $('card-results').hidden = false;
    $('card-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function describeCounts(c) {
    if (!c) return '';
    if (c.contours !== undefined) return `${fmtNum(c.contours)} polylines (${fmtNum(c.major_contours)} major), ${fmtNum(c.vertices)} vertices`;
    if (c.points !== undefined) return `${fmtNum(c.points)} POINT`;
    if (c.faces !== undefined) return `${fmtNum(c.faces)} 3DFACE`;
    return '';
  }

  async function start() {
    const problem = intervalProblem() || bboxProblem();
    if (problem) { setStatus('run-status', 'error', problem); return; }
    $('log').replaceChildren();
    $('card-results').hidden = true;
    setStatus('run-status', 'busy', 'Running…');
    $('bar-fill').style.width = '0%';
    setRunning(true);
    const cfg = {
      tiles: state.tilePaths.slice(),
      bbox: currentBbox(),
      outputs: selectedOutputs(),
      contour_interval: parseNum($('interval')),
      major_interval: parseNum($('major')),
      prefix: $('prefix').value.trim() || 'KAGIS',
      make_zip: $('make-zip').checked,
    };
    try {
      await api.startJob(cfg);
    } catch (err) {
      setRunning(false);
      setStatus('run-status', 'error', err.message);
    }
  }

  // ------------------------------------------------------------ wiring

  function bindEvents() {
    $('btn-pick-files').addEventListener('click', async () => {
      const paths = await api.pickTiles();
      if (paths.length) await addPaths(paths);
    });
    $('btn-pick-folder').addEventListener('click', async () => {
      const paths = await api.pickTileFolder();
      if (paths.length === 0) {
        setStatus('tile-status', 'warn', 'No dgm_*.tif files were found in that folder.');
        return;
      }
      await addPaths(paths);
    });
    $('btn-clear').addEventListener('click', async () => {
      state.tilePaths = [];
      await refreshInspect();
    });
    $('btn-pick-output').addEventListener('click', async () => {
      const dir = await api.pickOutputDir();
      if (dir) {
        state.outputDir = dir;
        $('output-path').textContent = dir;
      }
      updateStartState();
    });

    const dz = $('dropzone');
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', async (e) => {
      e.preventDefault();
      dz.classList.remove('over');
      if (state.running) return;
      const paths = api.pathsForDroppedFiles(e.dataTransfer && e.dataTransfer.files);
      if (paths.length) await addPaths(paths);
    });
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => e.preventDefault());

    $('use-bbox').addEventListener('change', async () => { updateHints(); await refreshInspect(); });
    for (const id of ['bb-xmin', 'bb-ymin', 'bb-xmax', 'bb-ymax']) {
      $(id).addEventListener('input', updateHints);
    }
    $('btn-check-cover').addEventListener('click', async () => {
      await refreshInspect();
      if (!currentBbox()) setStatus('coverage-status', 'warn', bboxProblem() || 'Enter a valid box.');
    });

    for (const id of ['out-contours', 'out-points', 'out-tin']) $(id).addEventListener('change', updateStartState);
    for (const id of ['interval', 'major']) $(id).addEventListener('input', updateHints);

    $('btn-start').addEventListener('click', start);
    $('btn-cancel').addEventListener('click', async () => {
      $('btn-cancel').disabled = true;
      appendLog('Cancelling…', 'warn');
      await api.cancelJob();
    });
    $('btn-open-output').addEventListener('click', async () => {
      const first = state.lastOutputs[0];
      const folder = state.outputDir;
      try {
        await api.openFolder(folder || (first && first.path));
      } catch (err) {
        setStatus('run-status', 'error', err.message);
      }
    });
  }

  async function init() {
    bindEvents();
    api.onJobEvent(onJobEvent);
    try {
      const info = await api.appInfo();
      $('version').textContent = `v${info.version}`;
    } catch (_e) { /* optional */ }
    setStatus('tile-status', '', 'No tiles loaded yet.');
    updateHints();
    updateStartState();
  }

  init();
})();
