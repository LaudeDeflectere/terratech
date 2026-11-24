"""Job orchestration: validate, build the mosaic, write products, README and ZIP.

Outputs are first written into a hidden job folder inside the output folder and
moved into place only after everything succeeded. On failure the job folder is
removed, so no incomplete DXF is left behind.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import __version__
from .dxf import CONTOUR_LAYER, MAJOR_LAYER, POINT_LAYER, TIN_LAYER, DxfWriter
from .grid import DEFAULT_MAX_CELLS, build_mosaic, centre_coordinates, inner_coordinates, inner_view, make_plan
from .products import write_contours, write_points, write_tin
from .tiles import PROVENANCE_NOTE, InputError, load_tile_set, union_extent

_PREFIX = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_OUTPUTS = ('contours', 'points', 'tin')


@dataclass
class JobConfig:
    tiles: list
    bbox: list | None
    outputs: list
    contour_interval: float
    major_interval: float
    output_dir: str
    prefix: str = 'KAGIS'
    make_zip: bool = True
    max_cells: int = DEFAULT_MAX_CELLS

    @classmethod
    def from_dict(cls, d: dict) -> 'JobConfig':
        tiles = d.get('tiles') or []
        if not isinstance(tiles, list) or not tiles:
            raise InputError('Select at least one DGM tile.')
        outputs = d.get('outputs') or []
        if not outputs or any(o not in _OUTPUTS for o in outputs):
            raise InputError('Select at least one output: contours, points or tin.')
        try:
            interval = float(d.get('contour_interval', 1.0))
            major = float(d.get('major_interval', 5.0))
        except (TypeError, ValueError) as exc:
            raise InputError('Contour intervals must be numbers.') from exc
        if not (math.isfinite(interval) and interval > 0 and math.isfinite(major) and major > 0):
            raise InputError('Contour intervals must be positive numbers.')
        ratio = major / interval
        if abs(ratio - round(ratio)) > 1e-9 or round(ratio) < 1:
            raise InputError('The major contour interval must be a whole multiple of the contour interval.')
        prefix = str(d.get('prefix', 'KAGIS'))
        if not _PREFIX.match(prefix):
            raise InputError('The file prefix may only contain letters, digits, _ and -.')
        bbox = d.get('bbox')
        if bbox is not None:
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise InputError('The bounding box needs four numbers: xmin ymin xmax ymax.')
        return cls(tiles=[str(t) for t in tiles], bbox=bbox, outputs=list(outputs),
                   contour_interval=interval, major_interval=major,
                   output_dir=str(d.get('output_dir', '')), prefix=prefix,
                   make_zip=bool(d.get('make_zip', True)),
                   max_cells=int(d.get('max_cells', DEFAULT_MAX_CELLS)))


def _fmt_bbox(b):
    return f'{b[0]:.4f} {b[1]:.4f} {b[2]:.4f} {b[3]:.4f}'


def run_job(cfg: JobConfig, emit) -> dict:
    """Run the conversion. ``emit`` receives JSON-serialisable event dicts."""
    def progress(phase, fraction, message):
        emit({'event': 'progress', 'phase': phase, 'fraction': round(fraction, 4), 'message': message})

    if not cfg.output_dir:
        raise InputError('Choose an output folder.')
    out_dir = Path(cfg.output_dir)
    if not out_dir.is_dir():
        raise InputError(f'Output folder does not exist: {out_dir}')

    progress('validate', 0.0, 'Checking tiles')
    tiles, errors = load_tile_set(cfg.tiles)
    if errors:
        raise InputError(' | '.join(e['message'] for e in errors))
    for t in tiles:
        for w in t.warnings:
            emit({'event': 'warning', 'message': f'{t.name}: {w}'})

    plan = make_plan(tiles, cfg.bbox)
    union = union_extent(tiles)
    covered_req = None  # filled after the mosaic

    job_dir = out_dir / f'.dgm-job-{uuid.uuid4().hex[:10]}'
    job_dir.mkdir()
    emit({'event': 'job', 'job_dir': str(job_dir)})
    try:
        progress('mosaic', 0.0, 'Reading DGM tiles')
        mosaic = build_mosaic(
            tiles, plan, cfg.max_cells,
            progress=lambda i, n: progress('mosaic', i / n, f'Reading tile {i + 1} of {n}'))
        inner = inner_view(plan, mosaic.z)
        inner_valid = int(np.isfinite(inner).sum())
        total_req = plan.requested_cells
        covered_req = inner_valid / total_req if total_req else 0.0
        missing = total_req - inner_valid
        if missing > 0:
            emit({'event': 'warning', 'message':
                  f'Tiles do not completely cover the requested area: {missing:,} of {total_req:,} '
                  f'cell centres ({100 * (1 - covered_req):.2f} %) have no DGM data and are left out.'})
        if mosaic.conflicts:
            emit({'event': 'warning', 'message':
                  f'{mosaic.conflicts:,} overlapping cells disagree between tiles; the first tile was used.'})
        if inner_valid == 0:
            raise InputError('No DGM cells fall inside the requested area. Check the tiles and bounding box.')
        if plan.bbox_from_user:
            clip_box = plan.bbox
        else:
            clip_box = union

        z_inner_vals = inner[np.isfinite(inner)]
        elev_lo, elev_hi = float(z_inner_vals.min()), float(z_inner_vals.max())

        extents = clip_box
        xs_pad, ys_pad = centre_coordinates(plan)
        xs_in, ys_in = inner_coordinates(plan)
        counts = {}
        files = []

        if 'contours' in cfg.outputs:
            name = f'{cfg.prefix}_Hoehenlinien.dxf'
            w = DxfWriter(job_dir / name, [CONTOUR_LAYER, MAJOR_LAYER], extents)
            try:
                major_every = int(round(cfg.major_interval / cfg.contour_interval))
                counts['contours'] = write_contours(
                    w, mosaic.z, xs_pad, ys_pad, clip_box, cfg.contour_interval, major_every,
                    progress=lambda i, n: progress('contours', i / n, f'Contour level {i} of {n}'))
            finally:
                w.close()
            files.append((name, 'contours', counts['contours']))

        if 'points' in cfg.outputs:
            name = f'{cfg.prefix}_Hoehenpunkte.dxf'
            w = DxfWriter(job_dir / name, [POINT_LAYER], extents)
            try:
                n = write_points(w, inner, xs_in, ys_in,
                                 progress=lambda i, m: progress('points', i / m, f'Point row {i} of {m}'))
            finally:
                w.close()
            counts['points'] = n
            files.append((name, 'points', {'points': n}))

        if 'tin' in cfg.outputs:
            name = f'{cfg.prefix}_TIN.dxf'
            w = DxfWriter(job_dir / name, [TIN_LAYER], extents)
            try:
                n = write_tin(w, inner, xs_in, ys_in,
                              progress=lambda i, m: progress('tin', i / m, f'TIN row {i} of {m}'))
            finally:
                w.close()
            counts['faces'] = n
            files.append((name, 'tin', {'faces': n}))

        progress('readme', 0.95, 'Writing README')
        readme_name = f'{cfg.prefix}_README.txt'
        (job_dir / readme_name).write_text(
            _readme(cfg, tiles, plan, extents, covered_req, missing, total_req, mosaic,
                    elev_lo, elev_hi, counts),
            encoding='utf-8')

        zip_name = None
        if cfg.make_zip:
            progress('zip', 0.97, 'Creating ZIP')
            zip_name = f'{cfg.prefix}_DGM_EPSG31258.zip'
            with zipfile.ZipFile(job_dir / zip_name, 'w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as zf:
                for name, _, _ in files:
                    zf.write(job_dir / name, name)
                zf.write(job_dir / readme_name, 'README.txt')
            with zipfile.ZipFile(job_dir / zip_name) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise IOError(f'ZIP integrity check failed for {bad}')

        # Move finished files into the output folder.
        final = []
        to_move = [n for n, _, _ in files] + [readme_name] + ([zip_name] if zip_name else [])
        for name in to_move:
            dest = out_dir / name
            try:
                os.replace(job_dir / name, dest)
            except PermissionError as exc:
                raise InputError(f'Cannot replace {dest.name}; it may be open in another program. '
                                 'Close it and run again.') from exc
            final.append(dest)
        progress('done', 1.0, 'Finished')
        outputs = []
        for name, kind, c in files:
            p = out_dir / name
            outputs.append({'file': name, 'path': str(p), 'bytes': p.stat().st_size,
                            'kind': kind, 'counts': c})
        summary = {
            'event': 'done',
            'outputs': outputs,
            'readme': str(out_dir / readme_name),
            'zip': str(out_dir / zip_name) if zip_name else None,
            'zip_bytes': (out_dir / zip_name).stat().st_size if zip_name else None,
            'coverage_fraction': round(covered_req, 6),
            'elevation_min': elev_lo, 'elevation_max': elev_hi,
        }
        emit(summary)
        return summary
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def _readme(cfg, tiles, plan, extents, covered, missing, total_req, mosaic,
            elev_lo, elev_hi, counts) -> str:
    ver = __version__
    now = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        'TerraTech export',
        f'Generated: {now} by dgm-engine {ver}',
        '',
        'SOURCE',
        PROVENANCE_NOTE,
        'Source files (SHA-256 of each file as read):',
    ]
    for t in tiles:
        lines.append(f'  {t.name}  sha256={t.sha256}')
        lines.append(f'    bounds x {t.left:.2f} to {t.right:.2f}, y {t.bottom:.2f} to {t.top:.2f}; '
                     f'{t.width} x {t.height} cells, {t.res:g} m; '
                     f'elevation {t.elev_min:.3f} to {t.elev_max:.3f} m; '
                     f'valid cells {t.valid_cells:,}')
    lines += [
        '',
        'COORDINATES AND UNITS',
        'Coordinate system: EPSG:31258 (MGI / Austria GK M31). XY in metres, absolute values.',
        'Heights: original DGM values in metres. No vertical conversion.',
        'DXF (R12) does not reliably carry an EPSG code. In Civil 3D, assign EPSG:31258 to the drawing',
        'or the XREF/import manually; the files do not declare it.',
        f'$INSUNITS is set to metres.',
        '',
        'AREA',
        f'Requested bounding box (xmin ymin xmax ymax): '
        f'{_fmt_bbox(plan.bbox) if plan.bbox_from_user else "not given: full extent of the selected tiles"}',
        f'Output clip box: {_fmt_bbox(extents)}',
        f'Raster cell size: {plan.res:g} m',
        f'Cell centres inside the area (boundary centres included): {total_req:,}; with DGM data: '
        f'{total_req - missing:,} ({100 * covered:.2f} %).',
    ]
    if missing:
        lines.append(f'COVERAGE WARNING: {missing:,} cell centres in the requested area have no DGM data. '
                     'The selected tiles do not completely cover it; those areas are left out.')
    lines += [
        f'Elevation range of the cells used: {elev_lo:.3f} to {elev_hi:.3f} m.',
        '',
        'OUTPUTS AND COUNTS',
    ]
    if 'contours' in cfg.outputs:
        c = counts.get('contours', {})
        lines.append(f'{cfg.prefix}_Hoehenlinien.dxf: {c.get("contours", 0):,} 3D polylines '
                     f'({c.get("major_contours", 0):,} major on layer {MAJOR_LAYER}), '
                     f'{c.get("vertices", 0):,} vertices. Minor layer: {CONTOUR_LAYER}.')
        lines.append(f'  Contour interval {cfg.contour_interval:g} m; major every {cfg.major_interval:g} m.')
    if 'points' in cfg.outputs:
        lines.append(f'{cfg.prefix}_Hoehenpunkte.dxf: {counts.get("points", 0):,} POINT entities '
                     f'on layer {POINT_LAYER}, at valid raster-cell centres.')
    if 'tin' in cfg.outputs:
        lines.append(f'{cfg.prefix}_TIN.dxf: {counts.get("faces", 0):,} 3DFACE entities '
                     f'on layer {TIN_LAYER}.')
    lines += [
        '',
        'PROCESSING CHOICES',
        '- Only official DGM cells are used. Cells with NoData or non-finite values are excluded.',
        '- Gaps between tiles are never filled. No resampling, no shifted origin, no reprojection.',
        '- Contour heights are exact contour levels. Contour vertices are linear interpolations between',
        '  neighbouring original cell centres, so they are not measured points.',
        '  Contours are not generated where the source has no data (e.g. outside the tiles).',
        '  Contours are clipped to the output clip box.',
        '- Points: one POINT per valid cell centre inside the area, with the cell elevation.',
        '- TIN: flat-grid triangulation with two 3DFACE triangles per cell whose four corners are all valid.',
        '  It is not an optimised TIN, and cells touching NoData are skipped.',
        f'- Overlapping cells disagreeing between tiles: {mosaic.conflicts:,}.',
        '',
        'LIMITATIONS',
        'Element counts and file sizes can be very large for big areas, especially points and the TIN.',
        'The export has not been checked in AutoCAD or Civil 3D by the tool itself; the structure follows',
        'AutoCAD R12 DXF rules and was checked with an independent DXF reader.',
    ]
    return '\n'.join(lines) + '\n'
