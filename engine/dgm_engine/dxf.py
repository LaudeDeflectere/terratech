"""Streaming writer for ASCII AutoCAD R12 (AC1009) DXF files.

R12 is used because every AutoCAD and Civil 3D release reads it. Entities are
written as they are produced; nothing is accumulated in memory. The file uses
CRLF line endings and ASCII text only. DXF does not reliably carry an EPSG code;
the README tells the user to assign EPSG:31258 in Civil 3D.
"""
from __future__ import annotations

import numpy as np

CONTOUR_LAYER = 'HOEHENLINIEN'
MAJOR_LAYER = 'HAUPTHOEHENLINIEN'
POINT_LAYER = 'DGM_PUNKTE_1M'
TIN_LAYER = 'DGM_TIN_3DFACE'

_LAYER_COLOURS = {CONTOUR_LAYER: 8, MAJOR_LAYER: 1, POINT_LAYER: 7, TIN_LAYER: 8}


class DxfWriter:
    def __init__(self, path, layers, extents):
        """layers: names of layers to declare. extents: (xmin, ymin, xmax, ymax)."""
        self.path = path
        self.f = open(path, 'w', encoding='ascii', newline='\r\n', buffering=1 << 20)
        self._write_header(layers, extents)
        self.closed = False

    def _write_header(self, layers, extents):
        xmin, ymin, xmax, ymax = extents
        w = self.f.write
        w('0\nSECTION\n2\nHEADER\n')
        w('9\n$ACADVER\n1\nAC1009\n')
        w('9\n$INSUNITS\n70\n6\n')          # 6 = metres
        w('9\n$MEASUREMENT\n70\n1\n')       # 1 = metric
        w('9\n$LUNITS\n70\n2\n9\n$LUPREC\n70\n4\n')
        w(f'9\n$EXTMIN\n10\n{xmin:.4f}\n20\n{ymin:.4f}\n30\n0.0000\n')
        w(f'9\n$EXTMAX\n10\n{xmax:.4f}\n20\n{ymax:.4f}\n30\n0.0000\n')
        w('0\nENDSEC\n')
        w('0\nSECTION\n2\nTABLES\n')
        w('0\nTABLE\n2\nLTYPE\n70\n1\n')
        w('0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0.0\n')
        w('0\nENDTAB\n')
        w('0\nTABLE\n2\nSTYLE\n70\n1\n')
        w('0\nSTYLE\n2\nSTANDARD\n70\n0\n40\n0.0\n41\n1.0\n50\n0.0\n71\n0\n42\n0.2\n3\ntxt\n4\n\n')
        w('0\nENDTAB\n')
        w(f'0\nTABLE\n2\nLAYER\n70\n{len(layers)}\n')
        for name in layers:
            w(f'0\nLAYER\n2\n{name}\n70\n0\n62\n{_LAYER_COLOURS[name]}\n6\nCONTINUOUS\n')
        w('0\nENDTAB\n')
        w('0\nENDSEC\n')
        w('0\nSECTION\n2\nBLOCKS\n0\nENDSEC\n')
        w('0\nSECTION\n2\nENTITIES\n')

    def raw(self, text: str):
        self.f.write(text)

    def polyline(self, layer: str, pts: np.ndarray, z: float) -> int:
        """Write a 3D polyline at constant height z. Returns the vertex count."""
        closed = len(pts) >= 4 and pts[0, 0] == pts[-1, 0] and pts[0, 1] == pts[-1, 1]
        if closed:
            pts = pts[:-1]
        flags = 9 if closed else 8  # 8 = 3D polyline, 1 = closed
        parts = [f'0\nPOLYLINE\n8\n{layer}\n66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n{flags}\n']
        zs = f'{z:.4f}'
        for x, y in pts.tolist():
            parts.append(f'0\nVERTEX\n8\n{layer}\n10\n{x:.4f}\n20\n{y:.4f}\n30\n{zs}\n70\n32\n')
        parts.append(f'0\nSEQEND\n8\n{layer}\n')
        self.f.write(''.join(parts))
        return len(pts)

    def close(self):
        if not self.closed:
            self.f.write('0\nENDSEC\n0\nEOF\n')
            self.f.close()
            self.closed = True
