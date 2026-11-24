"""Command line interface.

  dgm-engine inspect TILE [TILE ...]     -> one JSON document on stdout
  dgm-engine convert --config job.json   -> JSON-lines events on stdout

stdout carries only JSON (ASCII); diagnostics go to stderr. Exit codes:
0 success, 2 invalid input, 1 unexpected internal error.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

from . import __version__
from .job import JobConfig, run_job
from .tiles import InputError, load_tile_set, union_extent


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=True) + '\n')
    sys.stdout.flush()


def _coverage(tiles, bbox):
    """Fraction of requested cell centres that have DGM data (reads only needed windows)."""
    import numpy as np

    from .grid import DEFAULT_MAX_CELLS, build_mosaic, inner_view, make_plan
    plan = make_plan(tiles, bbox)
    mosaic = build_mosaic(tiles, plan, DEFAULT_MAX_CELLS)
    covered = int(np.isfinite(inner_view(plan, mosaic.z)).sum())
    total = plan.requested_cells
    return {'bbox': list(bbox) if bbox is not None else None, 'requested_cells': total,
            'covered_cells': covered, 'fraction': covered / total if total else 0.0}


def cmd_inspect(paths, bbox=None) -> int:
    tiles, errors = load_tile_set(paths)
    doc = {
        'tiles': [t.to_dict() for t in tiles],
        'errors': errors,
        'union': None,
        'res': tiles[0].res if tiles else None,
        'crs': 'EPSG:31258',
        'coverage': None,
        'coverage_error': None,
    }
    if tiles:
        l, b, r, t = union_extent(tiles)
        doc['union'] = {'left': l, 'bottom': b, 'right': r, 'top': t}
        doc['elev_min'] = min(x.elev_min for x in tiles)
        doc['elev_max'] = max(x.elev_max for x in tiles)
        if bbox is not None:
            try:
                doc['coverage'] = _coverage(tiles, bbox)
            except InputError as exc:
                doc['coverage_error'] = str(exc)
    sys.stdout.write(json.dumps(doc, ensure_ascii=True) + '\n')
    sys.stdout.flush()
    return 0


def cmd_convert(config_path: str) -> int:
    with open(config_path, 'r', encoding='utf-8') as fh:
        cfg = JobConfig.from_dict(json.load(fh))
    run_job(cfg, _emit)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='dgm-engine', description='KAGIS DGM to DXF engine')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='cmd', required=True)
    pi = sub.add_parser('inspect', help='validate tiles and print metadata as JSON')
    pi.add_argument('tiles', nargs='+')
    pi.add_argument('--bbox', nargs=4, type=float, metavar=('XMIN', 'YMIN', 'XMAX', 'YMAX'),
                    help='optional area to check coverage for')
    pc = sub.add_parser('convert', help='run a conversion job')
    pc.add_argument('--config', required=True)
    args = p.parse_args(argv)
    try:
        if args.cmd == 'inspect':
            return cmd_inspect(args.tiles, args.bbox)
        return cmd_convert(args.config)
    except InputError as exc:
        _emit({'event': 'error', 'kind': 'input', 'message': str(exc)})
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - report any internal failure cleanly
        _emit({'event': 'error', 'kind': 'internal', 'message': f'Unexpected error: {exc}'})
        traceback.print_exc(file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
