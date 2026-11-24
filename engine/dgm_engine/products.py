"""Generators for contours, height points and the TIN.

All three read the mosaic arrays and stream entities to a DxfWriter.
"""
from __future__ import annotations

import math

import contourpy
import numpy as np
from shapely.geometry import LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry

from .dxf import MAJOR_LAYER, CONTOUR_LAYER, POINT_LAYER, TIN_LAYER


def _line_parts(geom: BaseGeometry):
    if geom.is_empty:
        return []
    if geom.geom_type == 'LineString':
        return [geom]
    if isinstance(geom, MultiLineString) or geom.geom_type == 'GeometryCollection':
        out = []
        for g in geom.geoms:
            out.extend(_line_parts(g))
        return out
    return []


def clip_polyline(coords: np.ndarray, clip_box, clip_geom) -> list:
    """Return the parts of an open or closed polyline that lie inside clip_box."""
    if len(coords) < 2:
        return []
    xmin, ymin, xmax, ymax = clip_box
    inside = ((coords[:, 0] >= xmin) & (coords[:, 0] <= xmax) &
              (coords[:, 1] >= ymin) & (coords[:, 1] <= ymax))
    if inside.all():
        return [coords]
    parts = _line_parts(LineString(coords).intersection(clip_geom))
    return [np.asarray(p.coords) for p in parts if len(p.coords) >= 2]


def write_contours(writer, z_pad: np.ndarray, xs: np.ndarray, ys_desc: np.ndarray,
                   clip_box, interval: float, major_every: int, progress=None):
    """Write 3D contour polylines. Returns counts dict.

    Heights are contour levels; contour vertices are linear interpolations
    between original raster cell centres (contourpy, corner_mask=False).
    """
    counts = {'contours': 0, 'major_contours': 0, 'vertices': 0}
    if not np.isfinite(z_pad).any():
        return counts
    zmin = float(np.nanmin(z_pad))
    zmax = float(np.nanmax(z_pad))
    k0 = math.ceil(zmin / interval - 1e-9)
    k1 = math.floor(zmax / interval + 1e-9)
    levels = range(k0, k1 + 1)
    if not levels:
        return counts

    z_masked = np.ma.masked_invalid(z_pad)
    # contourpy expects y ascending with matching z rows.
    gen = contourpy.contour_generator(
        x=xs, y=ys_desc[::-1], z=z_masked[::-1, :],
        name='serial', corner_mask=False, line_type='Separate')
    clip_geom = box(*clip_box)

    for i, k in enumerate(levels):
        level = k * interval
        is_major = major_every > 0 and k % major_every == 0
        layer = MAJOR_LAYER if is_major else CONTOUR_LAYER
        for line in gen.lines(level):
            for part in clip_polyline(np.asarray(line), clip_box, clip_geom):
                n = writer.polyline(layer, part, level)
                if n >= 2:
                    counts['contours'] += 1
                    counts['major_contours'] += int(is_major)
                    counts['vertices'] += n
        if progress is not None and (i % 5 == 0 or i == len(levels) - 1):
            progress(i + 1, len(levels))
    return counts


def write_points(writer, inner: np.ndarray, xs: np.ndarray, ys: np.ndarray, progress=None) -> int:
    """One POINT per valid cell centre, at the cell's real elevation."""
    valid = np.isfinite(inner)
    count = 0
    rows = inner.shape[0]
    for i in range(rows):
        cols = np.flatnonzero(valid[i])
        if cols.size:
            y = f'{ys[i]:.4f}'
            vals = inner[i, cols].tolist()
            xs_row = xs[cols].tolist()
            writer.raw(''.join(
                f'0\nPOINT\n8\n{POINT_LAYER}\n10\n{x:.4f}\n20\n{y}\n30\n{z:.4f}\n'
                for x, z in zip(xs_row, vals)))
            count += cols.size
        if progress is not None and (i % 100 == 0 or i == rows - 1):
            progress(i + 1, rows)
    return count


def write_tin(writer, inner: np.ndarray, xs: np.ndarray, ys: np.ndarray, progress=None) -> int:
    """Two 3DFACE triangles per cell whose four corners are all valid."""
    valid = np.isfinite(inner)
    quad = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    count = 0
    rows = inner.shape[0] - 1
    for i in range(rows):
        cols = np.flatnonzero(quad[i])
        if cols.size:
            parts = []
            for c in cols.tolist():
                xl, xr = f'{xs[c]:.4f}', f'{xs[c + 1]:.4f}'
                yn, ys_ = f'{ys[i]:.4f}', f'{ys[i + 1]:.4f}'
                nw, ne = f'{inner[i, c]:.4f}', f'{inner[i, c + 1]:.4f}'
                sw, se = f'{inner[i + 1, c]:.4f}', f'{inner[i + 1, c + 1]:.4f}'
                # Triangle 1: NW, SW, NE. Triangle 2: NE, SW, SE (4th corner repeats 3rd).
                parts.append(
                    f'0\n3DFACE\n8\n{TIN_LAYER}\n'
                    f'10\n{xl}\n20\n{yn}\n30\n{nw}\n'
                    f'11\n{xl}\n21\n{ys_}\n31\n{sw}\n'
                    f'12\n{xr}\n22\n{yn}\n32\n{ne}\n'
                    f'13\n{xr}\n23\n{yn}\n33\n{ne}\n')
                parts.append(
                    f'0\n3DFACE\n8\n{TIN_LAYER}\n'
                    f'10\n{xr}\n20\n{yn}\n30\n{ne}\n'
                    f'11\n{xl}\n21\n{ys_}\n31\n{sw}\n'
                    f'12\n{xr}\n22\n{ys_}\n32\n{se}\n'
                    f'13\n{xr}\n23\n{ys_}\n33\n{se}\n')
            writer.raw(''.join(parts))
            count += 2 * cols.size
        if progress is not None and (i % 100 == 0 or i == rows - 1):
            progress(i + 1, rows)
    return count
