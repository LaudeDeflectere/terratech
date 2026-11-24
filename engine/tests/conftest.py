"""Synthetic EPSG:31258 GeoTIFF helpers for the test suite."""
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

NODATA = -99999.0


def write_tile(path: Path, data, left, top, res=1.0, nodata=NODATA, epsg=31258, dtype='float32'):
    """Write a single-band GeoTIFF whose upper-left corner is (left, top)."""
    data = np.asarray(data, dtype=dtype)
    h, w = data.shape
    profile = dict(driver='GTiff', height=h, width=w, count=1, dtype=dtype,
                   crs=CRS.from_epsg(epsg), transform=from_origin(left, top, res, res))
    if nodata is not None:
        profile['nodata'] = nodata
    with rasterio.open(path, 'w', **profile) as ds:
        ds.write(data, 1)
    return path


def ramp(h, w, dx=0.0, dy=0.0, base=500.0):
    """Elevation = base + dx*col + dy*row (a plane); pure float32-exact values."""
    rows, cols = np.mgrid[0:h, 0:w]
    return (base + dx * cols + dy * rows).astype(np.float32)


def run_engine(config: dict, tmp_path: Path):
    """Run the convert job in-process and return (events, output_dir)."""
    from dgm_engine.job import JobConfig, run_job
    cfg = JobConfig.from_dict(config)
    events = []
    run_job(cfg, events.append)
    return events


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / 'out'
    d.mkdir()
    return d


def base_config(tiles, out_dir, **kw):
    cfg = {'tiles': [str(t) for t in tiles], 'bbox': None,
           'outputs': ['contours', 'points', 'tin'], 'contour_interval': 1.0,
           'major_interval': 5.0, 'output_dir': str(out_dir), 'prefix': 'T', 'make_zip': False}
    cfg.update(kw)
    return cfg


def done_event(events):
    return [e for e in events if e.get('event') == 'done'][-1]


def warnings_of(events):
    return [e['message'] for e in events if e.get('event') == 'warning']


__all__ = ['write_tile', 'ramp', 'run_engine', 'base_config', 'done_event', 'warnings_of', 'NODATA', 'json']
