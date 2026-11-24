"""Validation of KAGIS DGM (elevation) GeoTIFF tiles.

Rules enforced here (the engine never silently repairs an input):
  * file must be a readable single-band GeoTIFF named dgm_*.tif
  * names starting with dom_ are rejected (DOM = image product)
  * coordinate system must be EPSG:31258 (no reprojection)
  * north-up, square cells, one common cell size across all tiles
  * all tiles must lie on one shared 1-cell lattice (no shifted origins)
  * NoData is read from the file; non-finite values are always excluded
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError

TARGET_EPSG = 31258
PROVENANCE_NOTE = (
    'A file name cannot prove where a raster came from. Use only official KAGIS '
    'DGM (elevation) downloads; DOM, orthophoto and preview images are not accepted.'
)
_DOM = re.compile(r'^dom[_-]', re.IGNORECASE)
_DGM = re.compile(r'^dgm[_-]', re.IGNORECASE)
_TIF_SUFFIXES = {'.tif', '.tiff'}
_DTYPES = {'float32', 'float64', 'int16', 'int32', 'uint16', 'uint32'}
_EPS = 1e-6  # tolerance in cells for lattice alignment


class InputError(ValueError):
    """A user-facing problem with input data or parameters."""


@dataclass
class TileInfo:
    path: str
    name: str
    sha256: str
    width: int
    height: int
    res: float
    left: float
    top: float
    right: float
    bottom: float
    epsg: int
    nodata: float | None
    dtype: str
    elev_min: float
    elev_max: float
    valid_cells: int
    warnings: list = field(default_factory=list)
    # Upper-left cell index of this tile on the shared lattice (set by load_tile_set).
    col0: int = 0
    row0: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        # JSON cannot carry NaN; represent a NaN NoData explicitly.
        if self.nodata is not None and math.isnan(self.nodata):
            d['nodata'] = 'NaN'
        return d


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect_tile(path) -> TileInfo:
    """Validate one tile on its own and return its metadata."""
    path = Path(path)
    name = path.name
    if not path.is_file():
        raise InputError(f'{name}: file not found.')
    if path.suffix.lower() not in _TIF_SUFFIXES:
        raise InputError(f'{name}: not a GeoTIFF (.tif or .tiff).')
    if _DOM.match(name):
        raise InputError(f'{name}: rejected. Names starting with dom_ are DOM (image) '
                         f'products, not elevation. {PROVENANCE_NOTE}')
    if not _DGM.match(name):
        raise InputError(f'{name}: expected an elevation tile named dgm_*.tif. {PROVENANCE_NOTE}')

    try:
        ds = rasterio.open(path)
    except RasterioIOError as exc:
        raise InputError(f'{name}: cannot be read as a GeoTIFF ({exc}).') from exc

    with ds:
        if ds.count != 1:
            raise InputError(f'{name}: expected one band, found {ds.count}. '
                             'DGM tiles are single-band elevation rasters.')
        dtype = ds.dtypes[0]
        if dtype not in _DTYPES:
            raise InputError(f'{name}: unsupported pixel type {dtype} for elevation data.')
        epsg = ds.crs.to_epsg() if ds.crs is not None else None
        if epsg != TARGET_EPSG:
            if ds.crs is None:
                found = 'no coordinate system'
            elif epsg is not None:
                found = f'EPSG:{epsg}'
            else:
                found = ds.crs.to_string()
            raise InputError(
                f'{name}: coordinate system is {found}; EPSG:31258 is required. The tool does '
                'not reproject silently, because that would change heights and coordinates.')
        t = ds.transform
        if abs(t.b) > 1e-12 or abs(t.d) > 1e-12:
            raise InputError(f'{name}: rotated rasters are not supported (north-up grid required).')
        if t.a <= 0 or t.e >= 0:
            raise InputError(f'{name}: north-up grid required (positive x size, negative y size).')
        res = float(t.a)
        if abs(res + t.e) > 1e-9:
            raise InputError(f'{name}: cells are not square ({t.a} x {-t.e} m).')
        width, height = ds.width, ds.height
        nodata = None if ds.nodata is None else float(ds.nodata)
        data = ds.read(1).astype(np.float64)
        left, top = float(t.c), float(t.f)

    invalid = ~np.isfinite(data)
    if nodata is not None and not math.isnan(nodata):
        invalid |= data == nodata
    valid = ~invalid
    n_valid = int(valid.sum())
    if n_valid == 0:
        raise InputError(f'{name}: contains no valid elevation values.')

    warnings = []
    if nodata is None:
        warnings.append('No NoData value is declared in the file; only non-finite values are excluded.')
    if abs(res - 1.0) > 1e-9:
        warnings.append(f'Cell size is {res:g} m, not the 1 m KAGIS DGM resolution. Check the product.')

    return TileInfo(
        path=str(path.resolve()), name=name, sha256=_sha256(path),
        width=width, height=height, res=res,
        left=left, top=top,
        right=left + width * res, bottom=top - height * res,
        epsg=TARGET_EPSG, nodata=nodata, dtype=dtype,
        elev_min=float(data[valid].min()), elev_max=float(data[valid].max()),
        valid_cells=n_valid, warnings=warnings,
    )


def _compatibility_error(t: TileInfo, ref: TileInfo) -> str | None:
    if abs(t.res - ref.res) > 1e-9:
        return (f'cell size {t.res:g} m differs from {ref.res:g} m of the reference tile '
                f'{ref.name}.')
    fx = (t.left - ref.left) / ref.res
    fy = (ref.top - t.top) / ref.res
    if abs(fx - round(fx)) > _EPS or abs(fy - round(fy)) > _EPS:
        return (f'grid is not aligned with {ref.name} (offset {fx:.4f} x {fy:.4f} cells). '
                'All tiles must share one lattice.')
    return None


def load_tile_set(paths):
    """Validate many tiles.

    Returns (accepted_tiles, errors). ``errors`` is a list of {'file', 'message'}
    dicts for tiles that were rejected. Accepted tiles share one lattice; their
    ``col0``/``row0`` give each tile's position on it, and the returned origin
    (x0, y0) is the top-left corner of the union of accepted tiles.
    """
    unique, seen = [], set()
    for p in paths:
        key = str(Path(p).resolve())
        if key not in seen:
            seen.add(key)
            unique.append(Path(key))
    if not unique:
        raise InputError('No DGM tiles were given.')

    ok, errors = [], []
    for p in unique:
        try:
            ok.append(inspect_tile(p))
        except InputError as exc:
            errors.append({'file': p.name, 'message': str(exc)})
    if not ok:
        return [], errors

    # Reference = first tile of the most common cell size.
    sizes = {}
    for t in ok:
        sizes.setdefault(round(t.res, 9), []).append(t)
    ref = max(sizes.values(), key=len)[0]

    accepted = []
    for t in ok:
        msg = _compatibility_error(t, ref)
        if msg:
            errors.append({'file': t.name, 'message': f'{t.name}: rejected, {msg}'})
        else:
            accepted.append(t)
    if not accepted:
        return [], errors

    x0 = min(t.left for t in accepted)
    y0 = max(t.top for t in accepted)
    for t in accepted:
        t.col0 = int(round((t.left - x0) / t.res))
        t.row0 = int(round((y0 - t.top) / t.res))
    return accepted, errors


def union_extent(tiles):
    return (min(t.left for t in tiles), min(t.bottom for t in tiles),
            max(t.right for t in tiles), max(t.top for t in tiles))
