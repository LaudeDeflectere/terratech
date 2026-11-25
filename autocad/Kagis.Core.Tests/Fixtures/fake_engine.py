"""Stand-in for dgm-engine in tests: reads job.json and prints the same JSON-line events.

FAKE_ENGINE_MODE controls the behaviour: ok (default), error, crash.
"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:1] != ['convert'] or '--config' not in args:
    print('usage: convert --config job.json', file=sys.stderr)
    sys.exit(2)
cfg = json.loads(Path(args[args.index('--config') + 1]).read_text(encoding='utf-8'))
mode = os.environ.get('FAKE_ENGINE_MODE', 'ok')
out_dir = Path(cfg['output_dir'])

print(json.dumps({'event': 'progress', 'phase': 'mosaic', 'fraction': 0.5, 'message': 'Reading DGM tiles'}), flush=True)
if mode == 'error':
    print(json.dumps({'event': 'error', 'kind': 'input', 'message': 'No DGM cells fall inside the requested area.'}), flush=True)
    sys.exit(2)
if mode == 'crash':
    print('Traceback (most recent call last): boom', file=sys.stderr, flush=True)
    sys.exit(1)

name = cfg['prefix'] + '_Hoehenlinien.dxf'
(out_dir / name).write_text('0\nEOF\n', encoding='ascii')
print(json.dumps({'event': 'warning', 'message': 'test warning'}), flush=True)
print(json.dumps({'event': 'done', 'outputs': [
    {'file': name, 'path': str(out_dir / name), 'bytes': 6, 'kind': 'contours', 'counts': {'contours': 42}}],
    'readme': None, 'zip': None, 'coverage_fraction': 1.0}), flush=True)
