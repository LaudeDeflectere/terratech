"""Engine tests on small synthetic GeoTIFFs (EPSG:31258, 1 m cells)."""
import math
import os
import shutil
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from conftest import NODATA, base_config, done_event, ramp, run_engine, warnings_of, write_tile
from dgm_engine.dxf import MAJOR_LAYER, CONTOUR_LAYER, POINT_LAYER, TIN_LAYER
from dgm_engine.grid import build_mosaic, make_plan
from dgm_engine.job import JobConfig, run_job
from dgm_engine.tiles import InputError, inspect_tile, load_tile_set

# Tile origins: upper-left corner in EPSG:31258 metres.
X0, Y0 = 500000.0, 200000.0


def read_dxf(path):
    doc = ezdxf.readfile(str(path))
    assert doc.audit().has_errors is False
    return doc.modelspace()


def points_of(msp):
    return [(p.dxf.layer, p.dxf.location.x, p.dxf.location.y, p.dxf.location.z)
            for p in msp.query('POINT')]


def faces_of(msp):
    out = []
    for f in msp.query('3DFACE'):
        out.append([tuple(getattr(f.dxf, f'vtx{i}')) for i in range(4)] + [f.dxf.layer])
    return out


# ---------------------------------------------------------------- inputs

def test_valid_tile_metadata(tmp_path):
    p = write_tile(tmp_path / 'dgm_a.tif', ramp(10, 12, dx=1.0, dy=1.0), X0, Y0)
    t = inspect_tile(p)
    assert (t.width, t.height, t.res) == (12, 10, 1.0)
    assert t.epsg == 31258
    assert t.left == X0 and t.top == Y0 and t.right == X0 + 12 and t.bottom == Y0 - 10
    assert t.elev_min == 500.0 and t.elev_max == pytest.approx(500 + 11 + 9)


def test_rejects_dom_file(tmp_path):
    p = write_tile(tmp_path / 'dom_1.tif', ramp(4, 4), X0, Y0)
    with pytest.raises(InputError, match='dom_'):
        inspect_tile(p)


def test_rejects_non_dgm_name(tmp_path):
    p = write_tile(tmp_path / 'random.tif', ramp(4, 4), X0, Y0)
    with pytest.raises(InputError, match='dgm_'):
        inspect_tile(p)


def test_rejects_wrong_crs_without_reprojecting(tmp_path):
    p = write_tile(tmp_path / 'dgm_wgs.tif', ramp(4, 4), X0, Y0, epsg=25833)
    with pytest.raises(InputError, match='EPSG:25833'):
        inspect_tile(p)


def test_misaligned_tile_is_rejected(tmp_path):
    a = write_tile(tmp_path / 'dgm_a.tif', ramp(10, 10), X0, Y0)
    b = write_tile(tmp_path / 'dgm_b.tif', ramp(10, 10), X0 + 10.5, Y0)
    accepted, errors = load_tile_set([a, b])
    assert [t.name for t in accepted] == ['dgm_a.tif']
    assert 'not aligned' in errors[0]['message']


def test_different_resolution_is_rejected(tmp_path):
    a = write_tile(tmp_path / 'dgm_a.tif', ramp(10, 10), X0, Y0, res=1.0)
    b = write_tile(tmp_path / 'dgm_b.tif', ramp(5, 5), X0 + 10, Y0, res=2.0)
    accepted, errors = load_tile_set([a, b])
    assert len(accepted) == 1 and 'cell size' in errors[0]['message']


def test_inspect_reports_nan_nodata_as_text(tmp_path):
    d = ramp(4, 4)
    p = write_tile(tmp_path / 'dgm_nan.tif', d, X0, Y0, nodata=float('nan'))
    t = inspect_tile(p)
    assert t.to_dict()['nodata'] == 'NaN'


# ---------------------------------------------------------------- geometry

def test_seam_between_tiles_has_no_gap_or_duplicate(tmp_path, out_dir):
    left = write_tile(tmp_path / 'dgm_l.tif', ramp(6, 10, dx=1.0), X0, Y0)
    right = write_tile(tmp_path / 'dgm_r.tif', ramp(6, 10, dx=1.0), X0 + 10, Y0)
    run_engine(base_config([left, right], out_dir, outputs=['points']), tmp_path)
    xy = [(round(x, 4), round(y, 4)) for _, x, y, _ in points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))]
    assert len(xy) == 20 * 6
    assert len(set(xy)) == 20 * 6  # every centre exactly once: no gap, no duplicate at the seam
    assert {x for x, _ in xy} == {X0 + 0.5 + c for c in range(20)}


def test_point_z_equals_raster_value_and_centre(tmp_path, out_dir):
    data = np.arange(30, dtype=np.float32).reshape(5, 6) + 100.0
    p = write_tile(tmp_path / 'dgm_v.tif', data, X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['points']), tmp_path)
    pts = points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))
    assert len(pts) == 30
    lookup = {(round(x, 4), round(y, 4)): z for _, x, y, z in pts}
    for r in range(5):
        for c in range(6):
            key = (round(X0 + c + 0.5, 4), round(Y0 - r - 0.5, 4))
            assert lookup[key] == pytest.approx(float(data[r, c]), abs=1e-4)


def test_bbox_clips_points_to_centres_inside(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_b.tif', ramp(20, 20), X0, Y0)
    # Box x 500003..500010, y 199990..200000  -> centres c=3..9 (7 cols), r=10..19 (10 rows)
    cfg = base_config([p], out_dir, outputs=['points'], bbox=[X0 + 3, Y0 - 10, X0 + 10, Y0])
    run_engine(cfg, tmp_path)
    pts = points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))
    assert len(pts) == 7 * 10
    for _, x, y, _ in pts:
        assert X0 + 3 <= x <= X0 + 10 and Y0 - 10 <= y <= Y0


def test_bbox_outside_tiles_is_an_error(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_o.tif', ramp(5, 5), X0, Y0)
    with pytest.raises(InputError, match='does not overlap'):
        run_engine(base_config([p], out_dir, bbox=[0, 0, 10, 10]), tmp_path)


def test_partial_coverage_is_reported_and_no_zero_fill(tmp_path, out_dir):
    # Two tiles with a 5 m gap between them (no NoData declared).
    a = write_tile(tmp_path / 'dgm_a.tif', ramp(4, 4, base=700.0), X0, Y0, nodata=None)
    b = write_tile(tmp_path / 'dgm_b.tif', ramp(4, 4, base=700.0), X0 + 9, Y0, nodata=None)
    events = run_engine(base_config([a, b], out_dir, outputs=['points'],
                                    bbox=[X0, Y0 - 4, X0 + 13, Y0]), tmp_path)
    assert any('do not completely cover' in w for w in warnings_of(events))
    pts = points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))
    # Requested centres: columns 0..12 x 4 rows = 52; tiles supply 16 + 16 = 32.
    assert len(pts) == 32
    assert all(z >= 700.0 for _, _, _, z in pts)  # no fabricated 0 m values


# ---------------------------------------------------------------- NoData

def test_nodata_cells_produce_no_points_and_no_tin_faces(tmp_path, out_dir):
    data = ramp(5, 5)
    data[2, 2] = NODATA
    p = write_tile(tmp_path / 'dgm_n.tif', data, X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['points', 'tin']), tmp_path)
    pts = points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))
    assert len(pts) == 24
    hole = (round(X0 + 2.5, 4), round(Y0 - 2.5, 4))
    assert all((round(x, 4), round(y, 4)) != hole for _, x, y, _ in pts)
    # Quads: 4x4 = 16 cells; the 4 touching (2,2) are skipped -> 12 cells -> 24 faces.
    faces = faces_of(read_dxf(out_dir / 'T_TIN.dxf'))
    assert len(faces) == 24
    for f in faces:
        assert all(abs(v[2] - NODATA) > 1 for v in f[:4])


def test_nodata_value_never_appears_as_elevation(tmp_path, out_dir):
    data = ramp(4, 4)
    data[0, 0] = NODATA
    p = write_tile(tmp_path / 'dgm_nd.tif', data, X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['points']), tmp_path)
    zs = [z for _, _, _, z in points_of(read_dxf(out_dir / 'T_Hoehenpunkte.dxf'))]
    assert len(zs) == 15 and min(zs) > 0


# ---------------------------------------------------------------- TIN / counts

def test_tin_face_count_is_two_per_full_quad(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_t.tif', ramp(7, 9), X0, Y0)
    events = run_engine(base_config([p], out_dir, outputs=['tin']), tmp_path)
    assert done_event(events)['outputs'][0]['counts']['faces'] == 2 * 6 * 8
    assert len(faces_of(read_dxf(out_dir / 'T_TIN.dxf'))) == 2 * 6 * 8


def test_tin_faces_use_layer_and_real_heights(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_h.tif', ramp(3, 3, dx=2.0), X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['tin']), tmp_path)
    faces = faces_of(read_dxf(out_dir / 'T_TIN.dxf'))
    assert {f[4] for f in faces} == {TIN_LAYER}
    # z = 500 + 2*col on 3 columns -> heights 500, 502, 504 only.
    z_values = {round(v[2], 4) for f in faces for v in f[:4]}
    assert z_values == {500.0, 502.0, 504.0}


# ---------------------------------------------------------------- contours

def test_contours_on_plane_are_exact_and_layered(tmp_path, out_dir):
    # z = 500 + col (x-ramp): contours are vertical lines at x = X0 + level - 500 + 0.5.
    p = write_tile(tmp_path / 'dgm_c.tif', ramp(20, 20, dx=1.0), X0, Y0)
    events = run_engine(base_config([p], out_dir, outputs=['contours'],
                                    contour_interval=1.0, major_interval=5.0), tmp_path)
    msp = read_dxf(out_dir / 'T_Hoehenlinien.dxf')
    lines = list(msp.query('POLYLINE'))
    assert lines, 'no contours written'
    major = [pl for pl in lines if pl.dxf.layer == MAJOR_LAYER]
    minor = [pl for pl in lines if pl.dxf.layer == CONTOUR_LAYER]
    assert len(major) > 0 and len(minor) > 0
    for pl in lines:
        verts = [v.dxf.location for v in pl.vertices]
        level = verts[0].z
        assert all(abs(v.z - level) < 1e-6 for v in verts), 'Z must equal the contour level'
        # Plane z = 500 + col: level L lies on column L-500, i.e. x-centre X0 + (L-500) + 0.5.
        assert all(abs(v.x - (X0 + level - 500.0 + 0.5)) < 1e-6 for v in verts)
    # Major contours are exactly the multiples of 5 m, on the major layer only.
    for pl in major:
        assert round(pl.vertices[0].dxf.location.z) % 5 == 0
    for pl in minor:
        assert round(pl.vertices[0].dxf.location.z) % 5 != 0
    assert done_event(events)['outputs'][0]['counts']['major_contours'] == len(major)


def test_contour_positions_match_linear_interpolation(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_i.tif', ramp(12, 12, dx=0.5), X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['contours'], contour_interval=1.0,
                           major_interval=5.0), tmp_path)
    msp = read_dxf(out_dir / 'T_Hoehenlinien.dxf')
    for pl in msp.query('POLYLINE'):
        verts = [v.dxf.location for v in pl.vertices]
        level = verts[0].z
        # Plane z = 500 + 0.5*col: contour at level L is at col = 2*(L-500); x-centre = X0 + col + 0.5
        expected_x = X0 + 2 * (level - 500.0) + 0.5
        for v in verts:
            assert v.x == pytest.approx(expected_x, abs=1e-3)


def test_contours_clipped_to_bbox(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_k.tif', ramp(30, 30, dx=1.0), X0, Y0)
    bbox = [X0 + 5.25, Y0 - 25.0, X0 + 12.75, Y0 - 3.5]
    run_engine(base_config([p], out_dir, outputs=['contours'], bbox=bbox), tmp_path)
    for pl in read_dxf(out_dir / 'T_Hoehenlinien.dxf').query('POLYLINE'):
        for v in pl.vertices:
            loc = v.dxf.location
            assert bbox[0] - 1e-6 <= loc.x <= bbox[2] + 1e-6
            assert bbox[1] - 1e-6 <= loc.y <= bbox[3] + 1e-6


# ---------------------------------------------------------------- DXF / outputs

def test_dxf_is_ascii_r12_metres_and_declares_layers(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_x.tif', ramp(6, 6), X0, Y0)
    run_engine(base_config([p], out_dir, outputs=['contours', 'points', 'tin']), tmp_path)
    raw = (out_dir / 'T_TIN.dxf').read_bytes()
    raw.decode('ascii')
    assert b'\r\n' in raw
    text = raw.decode('ascii')
    assert '$INSUNITS' in text and '$ACADVER' in text and 'AC1009' in text
    doc = ezdxf.readfile(str(out_dir / 'T_TIN.dxf'))
    assert doc.dxfversion == 'AC1009'
    assert TIN_LAYER in doc.layers
    assert doc.header['$INSUNITS'] == 6


def test_outputs_and_readme_and_zip(tmp_path, out_dir):
    import zipfile
    p = write_tile(tmp_path / 'dgm_z.tif', ramp(6, 6), X0, Y0)
    cfg = base_config([p], out_dir, make_zip=True)
    events = run_engine(cfg, tmp_path)
    done = done_event(events)
    names = sorted(os.listdir(out_dir))
    assert 'T_README.txt' in names and 'T_DGM_EPSG31258.zip' in names
    assert not any(n.startswith('.dgm-job') for n in names)
    with zipfile.ZipFile(out_dir / 'T_DGM_EPSG31258.zip') as zf:
        assert set(zf.namelist()) == {'T_Hoehenlinien.dxf', 'T_Hoehenpunkte.dxf', 'T_TIN.dxf', 'README.txt'}
        assert zf.testzip() is None
    readme = (out_dir / 'T_README.txt').read_text(encoding='utf-8')
    for needle in ('EPSG:31258', 'dgm_z.tif', 'sha256=', 'linear interpolations', 'metres'):
        assert needle in readme
    assert done['zip_bytes'] > 0


# ---------------------------------------------------------------- failure paths

def test_cancelled_job_leaves_no_partial_output(tmp_path, out_dir):
    p = write_tile(tmp_path / 'dgm_cancel.tif', ramp(40, 40, dx=1.0), X0, Y0)
    cfg = JobConfig.from_dict(base_config([p], out_dir))

    class Cancelled(Exception):
        pass

    def emit(ev):
        if ev.get('event') == 'progress' and ev.get('phase') == 'contours' and ev['fraction'] > 0.3:
            raise Cancelled()

    with pytest.raises(Cancelled):
        run_job(cfg, emit)
    assert [n for n in os.listdir(out_dir)] == []


def test_contour_interval_rules():
    base = dict(tiles=['x'], outputs=['contours'], output_dir='.')
    with pytest.raises(InputError, match='whole multiple'):
        JobConfig.from_dict({**base, 'contour_interval': 2.0, 'major_interval': 5.0})
    with pytest.raises(InputError, match='positive'):
        JobConfig.from_dict({**base, 'contour_interval': 0})
    with pytest.raises(InputError, match='prefix'):
        JobConfig.from_dict({**base, 'prefix': '../evil'})
    ok = JobConfig.from_dict({**base, 'contour_interval': 0.5, 'major_interval': 2.5})
    assert round(ok.major_interval / ok.contour_interval) == 5


def test_area_limit_is_enforced(tmp_path):
    p = write_tile(tmp_path / 'dgm_big.tif', ramp(50, 50), X0, Y0)
    tiles, _ = load_tile_set([p])
    plan = make_plan(tiles, None)
    with pytest.raises(InputError, match='limit'):
        build_mosaic(tiles, plan, max_cells=100)


def test_full_extent_when_bbox_omitted(tmp_path, out_dir):
    a = write_tile(tmp_path / 'dgm_p.tif', ramp(5, 5), X0, Y0)
    b = write_tile(tmp_path / 'dgm_q.tif', ramp(5, 5), X0, Y0 - 5)
    events = run_engine(base_config([a, b], out_dir, outputs=['points']), tmp_path)
    assert done_event(events)['outputs'][0]['counts']['points'] == 50
    assert not any('do not completely cover' in w for w in warnings_of(events))


def test_overlapping_tiles_with_same_values_have_no_conflicts(tmp_path, out_dir):
    a = write_tile(tmp_path / 'dgm_o1.tif', ramp(6, 6), X0, Y0)
    b = write_tile(tmp_path / 'dgm_o2.tif', ramp(6, 6), X0 + 3, Y0)
    events = run_engine(base_config([a, b], out_dir, outputs=['points']), tmp_path)
    assert done_event(events)['outputs'][0]['counts']['points'] == 6 * 9


# ---------------------------------------------------------------- real-world (optional)

REAL = os.environ.get('DGM_REAL_TILE_DIR')


@pytest.mark.skipif(not REAL, reason='set DGM_REAL_TILE_DIR to a folder with official dgm_*.tif tiles')
def test_real_world_tiles(tmp_path, out_dir):
    tiles = sorted(Path(REAL).glob('dgm_*.tif'))
    assert tiles
    events = run_engine(base_config(tiles, out_dir, outputs=['contours', 'points', 'tin'],
                                    make_zip=True), tmp_path)
    done = done_event(events)
    pts = next(o for o in done['outputs'] if o['kind'] == 'points')['counts']['points']
    valid = sum(inspect_tile(t).valid_cells for t in tiles)
    assert pts == valid  # every valid cell becomes exactly one point when no bbox is given
    msp = read_dxf(out_dir / next(o['file'] for o in done['outputs'] if o['kind'] == 'contours'))
    assert len(msp.query('POLYLINE')) > 0
