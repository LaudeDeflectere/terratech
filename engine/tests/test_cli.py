"""CLI contract tests: JSON on stdout, coverage check, error events."""
import json
import subprocess
import sys

from conftest import ramp, write_tile

X0, Y0 = 500000.0, 200000.0


def _run(args):
    return subprocess.run([sys.executable, '-m', 'dgm_engine', *args],
                          capture_output=True, text=True, timeout=120)


def test_inspect_json_and_coverage(tmp_path):
    a = write_tile(tmp_path / 'dgm_a.tif', ramp(10, 10), X0, Y0)
    b = write_tile(tmp_path / 'dgm_b.tif', ramp(10, 10), X0 + 10, Y0)
    r = _run(['inspect', '--bbox', str(X0), str(Y0 - 10), str(X0 + 20), str(Y0), '--', str(a), str(b)])
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)  # stdout must be pure JSON
    assert len(doc['tiles']) == 2 and doc['errors'] == []
    assert doc['union'] == {'left': X0, 'bottom': Y0 - 10, 'right': X0 + 20, 'top': Y0}
    assert doc['coverage']['fraction'] == 1.0
    assert doc['coverage']['requested_cells'] == 200


def test_inspect_partial_coverage_fraction(tmp_path):
    a = write_tile(tmp_path / 'dgm_a.tif', ramp(10, 10), X0, Y0)
    r = _run(['inspect', '--bbox', str(X0), str(Y0 - 10), str(X0 + 20), str(Y0), '--', str(a)])
    doc = json.loads(r.stdout)
    assert doc['coverage']['covered_cells'] == 100
    assert doc['coverage']['requested_cells'] == 200
    assert abs(doc['coverage']['fraction'] - 0.5) < 1e-12


def test_inspect_reports_rejected_dom_file_without_crashing(tmp_path):
    dgm = write_tile(tmp_path / 'dgm_ok.tif', ramp(4, 4), X0, Y0)
    dom = write_tile(tmp_path / 'dom_bad.tif', ramp(4, 4), X0, Y0)
    r = _run(['inspect', '--', str(dgm), str(dom)])
    doc = json.loads(r.stdout)
    assert len(doc['tiles']) == 1
    assert doc['errors'][0]['file'] == 'dom_bad.tif'
    assert 'dom_' in doc['errors'][0]['message']


def test_convert_input_error_emits_error_event(tmp_path):
    cfg = tmp_path / 'job.json'
    cfg.write_text(json.dumps({'tiles': [str(tmp_path / 'dgm_missing.tif')], 'outputs': ['points'],
                               'output_dir': str(tmp_path)}))
    r = _run(['convert', '--config', str(cfg)])
    assert r.returncode == 2
    events = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert events[-1]['event'] == 'error' and events[-1]['kind'] == 'input'
