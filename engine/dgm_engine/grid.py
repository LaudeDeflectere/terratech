"""Shared 1-cell lattice, requested-area window and mosaic construction.

Global lattice indices: column c covers x in [x0 + c*res, x0 + (c+1)*res);
row r covers y in (y0 - (r+1)*res, y0 - r*res]. Cell centres are at +0.5.
Only cell centres inside the requested bounding box are selected for output.
Gaps between tiles are NaN in the mosaic and are never filled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import Window

from .tiles import InputError, TileInfo, union_extent

DEFAULT_MAX_CELLS = 60_000_000  # about 240 MB of float32 for the working window
_EPS = 1e-7


@dataclass
class Plan:
    res: float
    x0: float            # left edge of the union of tiles
    y0: float            # top edge of the union of tiles
    bbox: tuple          # (xmin, ymin, xmax, ymax) clip box in EPSG:31258 metres
    bbox_from_user: bool
    # Requested centre window (global lattice indices, inclusive), unclamped.
    req_c0: int
    req_c1: int
    req_r0: int
    req_r1: int
    # Centre window actually read (clamped to the tile union).
    c0: int
    c1: int
    r0: int
    r1: int
    # Mosaic window = centre window + 1 cell of padding, clamped to the union.
    pc0: int
    pc1: int
    pr0: int
    pr1: int
    union_cols: int
    union_rows: int

    @property
    def requested_cells(self) -> int:
        return (self.req_c1 - self.req_c0 + 1) * (self.req_r1 - self.req_r0 + 1)

    @property
    def inner_shape(self):
        return (self.r1 - self.r0 + 1, self.c1 - self.c0 + 1)

    @property
    def padded_shape(self):
        return (self.pr1 - self.pr0 + 1, self.pc1 - self.pc0 + 1)


def make_plan(tiles: list[TileInfo], bbox_user) -> Plan:
    if not tiles:
        raise InputError('No valid tiles to process.')
    res = tiles[0].res
    ul = union_extent(tiles)  # (left, bottom, right, top)
    x0, y0 = ul[0], ul[3]
    union_cols = int(round((ul[2] - ul[0]) / res))
    union_rows = int(round((ul[3] - ul[1]) / res))

    if bbox_user is None:
        bbox = ul
        from_user = False
    else:
        xmin, ymin, xmax, ymax = (float(v) for v in bbox_user)
        if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)):
            raise InputError('The bounding box must contain finite numbers.')
        if not (xmin < xmax and ymin < ymax):
            raise InputError('The bounding box must be given as xmin ymin xmax ymax with xmin < xmax and ymin < ymax.')
        if xmax <= ul[0] or xmin >= ul[2] or ymax <= ul[1] or ymin >= ul[3]:
            raise InputError('The requested bounding box does not overlap any selected tile.')
        bbox = (xmin, ymin, xmax, ymax)
        from_user = True

    xmin, ymin, xmax, ymax = bbox
    # Pixel centres (c + 0.5) inside the box, with a tolerance for exact boundary hits.
    req_c0 = math.ceil((xmin - x0) / res - 0.5 - _EPS)
    req_c1 = math.floor((xmax - x0) / res - 0.5 + _EPS)
    req_r0 = math.ceil((y0 - ymax) / res - 0.5 - _EPS)
    req_r1 = math.floor((y0 - ymin) / res - 0.5 + _EPS)
    if req_c1 < req_c0 or req_r1 < req_r0:
        raise InputError('The requested area contains no raster-cell centres.')

    c0, c1 = max(req_c0, 0), min(req_c1, union_cols - 1)
    r0, r1 = max(req_r0, 0), min(req_r1, union_rows - 1)
    if c1 < c0 or r1 < r0:
        raise InputError('The requested area contains no raster-cell centres of the selected tiles.')

    pc0, pc1 = max(c0 - 1, 0), min(c1 + 1, union_cols - 1)
    pr0, pr1 = max(r0 - 1, 0), min(r1 + 1, union_rows - 1)

    return Plan(res=res, x0=x0, y0=y0, bbox=bbox, bbox_from_user=from_user,
                req_c0=req_c0, req_c1=req_c1, req_r0=req_r0, req_r1=req_r1,
                c0=c0, c1=c1, r0=r0, r1=r1,
                pc0=pc0, pc1=pc1, pr0=pr0, pr1=pr1,
                union_cols=union_cols, union_rows=union_rows)


@dataclass
class Mosaic:
    z: np.ndarray          # float32 (padded window), NaN = no data
    conflicts: int         # overlapping cells whose values disagree
    tiles_used: int


def build_mosaic(tiles: list[TileInfo], plan: Plan, max_cells: int, progress=None) -> Mosaic:
    shape = plan.padded_shape
    cells = shape[0] * shape[1]
    if cells > max_cells:
        raise InputError(
            f'The requested area needs {cells:,} raster cells in memory; the limit is '
            f'{max_cells:,}. Split the area into smaller bounding boxes.')
    z = np.full(shape, np.nan, dtype=np.float32)
    conflicts = 0
    used = 0
    for i, t in enumerate(tiles):
        tc0, tc1 = t.col0, t.col0 + t.width - 1
        tr0, tr1 = t.row0, t.row0 + t.height - 1
        ic0, ic1 = max(tc0, plan.pc0), min(tc1, plan.pc1)
        ir0, ir1 = max(tr0, plan.pr0), min(tr1, plan.pr1)
        if progress is not None:
            progress(i, len(tiles))
        if ic1 < ic0 or ir1 < ir0:
            continue
        used += 1
        with rasterio.open(t.path) as ds:
            win = Window(col_off=ic0 - tc0, row_off=ir0 - tr0,
                         width=ic1 - ic0 + 1, height=ir1 - ir0 + 1)
            arr = ds.read(1, window=win).astype(np.float32)
        bad = ~np.isfinite(arr)
        if t.nodata is not None and not math.isnan(t.nodata):
            bad |= arr == np.float32(t.nodata)
        arr[bad] = np.nan
        dst = z[ir0 - plan.pr0: ir1 - plan.pr0 + 1, ic0 - plan.pc0: ic1 - plan.pc0 + 1]
        both = np.isfinite(dst) & np.isfinite(arr)
        conflicts += int(np.count_nonzero(both & (np.abs(dst - arr) > 1e-4)))
        fill = ~np.isfinite(dst) & np.isfinite(arr)
        dst[fill] = arr[fill]
    return Mosaic(z=z, conflicts=conflicts, tiles_used=used)


def inner_view(plan: Plan, z: np.ndarray) -> np.ndarray:
    """The part of the mosaic that lies inside the requested centre window."""
    r_off = plan.r0 - plan.pr0
    c_off = plan.c0 - plan.pc0
    h, w = plan.inner_shape
    return z[r_off:r_off + h, c_off:c_off + w]


def centre_coordinates(plan: Plan):
    """Cell-centre coordinates for the padded window (xs ascending, ys descending)."""
    xs = plan.x0 + (plan.pc0 + np.arange(plan.padded_shape[1]) + 0.5) * plan.res
    ys = plan.y0 - (plan.pr0 + np.arange(plan.padded_shape[0]) + 0.5) * plan.res
    return xs, ys


def inner_coordinates(plan: Plan):
    xs = plan.x0 + (plan.c0 + np.arange(plan.inner_shape[1]) + 0.5) * plan.res
    ys = plan.y0 - (plan.r0 + np.arange(plan.inner_shape[0]) + 0.5) * plan.res
    return xs, ys
