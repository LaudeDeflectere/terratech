# KAGIS DGM to DXF

A desktop application (Electron, Windows first, Linux supported) that converts
official **KAGIS DGM** elevation GeoTIFF tiles (`dgm_*.tif`, EPSG:31258) into
ASCII **AutoCAD R12 DXF** files for AutoCAD and Civil 3D:

- **Contours** – 1 m height lines as 3D polylines with real Z, major contours on their own layer
- **Height points** – one `POINT` per DGM cell centre, at the cell's elevation (very large)
- **TIN** – `3DFACE` triangles between adjacent cells whose four corners are all valid (very large)

The end user does not need Python, GDAL, or pip: the conversion engine is bundled with the app.

## Using the app

1. **Tiles** – drop `dgm_*.tif` files onto the window, choose files, or choose a folder.
   Each tile is checked; accepted tiles show coordinate system, cell size, size in cells,
   bounds and elevation range. Rejected tiles are listed with the reason. A coverage map
   shows the tiles (and the requested area, once set).
2. **Area (optional)** – tick *Limit to a bounding box* and enter `xmin ymin xmax ymax` in
   EPSG:31258 metres, then *Check coverage*. If the tiles do not completely cover the area,
   the app says so and states how many cell centres will be left out. Without a box, the
   full extent of the selected tiles is processed.
3. **Outputs** – contours are selected by default; points and TIN are optional because they
   are very large. Set the contour interval and the major interval (the major interval must be
   a whole multiple of the contour interval). Choose an output folder and a file prefix.
4. **Run** – progress, warnings and errors are shown while the engine runs in a separate
   process, so the window stays responsive. *Cancel* stops the job and removes all incomplete
   files. On success the app lists the files with sizes and element counts, and offers
   *Open output folder*. A ZIP with the selected DXFs and the README is created by default.

Each export contains a `README` with the source file names and SHA-256 hashes, bounds,
CRS, cell size, elevation range, element counts, and the processing choices.

## What the data and the DXF files mean

**Input validation.** The engine accepts only single-band GeoTIFFs in EPSG:31258 with
north-up, square cells of one common size, all on one shared 1-cell lattice. Files named
`dom_*` are rejected. A file name cannot prove a raster's provenance, so use official KAGIS
DGM downloads. Incompatible tiles are rejected with a reason; the tool never reprojects,
resamples, or shifts an origin silently. NoData is read from the file; non-finite values are
always excluded. Gaps between tiles are never filled.

**Contour heights are interpolated.** DGM values exist only at cell centres. Contour levels
are exact (e.g. 512.0 m), but each contour vertex is a linear interpolation between
neighbouring real cell centres (contourpy, no corner masking). The contour position is therefore
an estimate between measured cells, not a measured point. Contours are not drawn where the
source has no data.

**Points and TIN use real cells only.** Each point is at a valid cell centre with that cell's
elevation. The TIN is a flat-grid triangulation: two triangles per cell with all four corners
valid. It is not an optimised TIN, and cells touching NoData are skipped.

**Clipping.** Outputs are clipped to the requested bounding box (or to the tile extent if no box
is given). Only cell centres inside the box are used for points and TIN.

**Coordinates and units.** XY are absolute EPSG:31258 metres (no origin shift), Z are the
original DGM heights in metres. The DXF header sets `$INSUNITS` to metres.
**DXF does not reliably carry an EPSG code.** In Civil 3D, assign EPSG:31258 to the drawing or
the imported data manually.

**Layers.** Contours: `HOEHENLINIEN` (minor) and `HAUPTHOEHENLINIEN` (major). Points:
`DGM_PUNKTE_1M`. TIN: `DGM_TIN_3DFACE`.

**Sizes.** Points and TIN grow with the area: roughly 1.56 million points and 3.1 million faces
per 1250 × 1250 m tile. For the 1-tile test below, the outputs were 119 MB (points) and 693 MB
(TIN). Split large areas with bounding boxes; the engine refuses requests above a cell limit
(default 60 million cells, configurable per job) to protect memory.

## Architecture

```
app/       Electron shell: main process (IPC, job control, validation), preload (context bridge), renderer (UI only)
engine/    Python conversion engine (rasterio, numpy, contourpy, shapely) + tests, bundled by PyInstaller
```

- The renderer has `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, and a
  strict Content Security Policy. It reaches the main process only through the fixed functions
  exposed by `src/preload/preload.js`.
- All renderer input (paths, bounding box, prefix, intervals) is validated again in the main
  process (`src/main/validation.js`) before the engine runs. The engine is started with
  `spawn` and never through a shell.
- The engine writes into a hidden `.dgm-job-*` folder inside the output folder and moves finished
  files into place only at the end. On failure or cancel the folder is deleted.
- The engine streams entities to disk (no CAD entity lists are held in memory). Raster processing
  holds one window of float32 cells (bounded by the cell limit).
- The engine reports progress as JSON lines on stdout; diagnostics go to stderr.

Engine command line (also usable without the app):

```bash
dgm-engine inspect [--bbox XMIN YMIN XMAX YMAX] -- TILE...    # JSON metadata and coverage
dgm-engine convert --config job.json                          # JSON-line events
```

## Build and run

### Development (Linux or Windows, Python 3.12 recommended)

```bash
# Engine
cd engine
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q                       # synthetic-data test suite
DGM_REAL_TILE_DIR=/path/to/tiles python -m pytest -q   # optional real-world test

# App
cd ../app
npm install
npm start                                 # uses python -m dgm_engine from ../engine
npm test                                  # validation and engine bridge unit tests
```

Set `DGM_PYTHON` to choose the Python interpreter, or `DGM_ENGINE_EXE` to use an engine executable.

### Packaged builds

The engine must be built on the same platform as the app (PyInstaller does not cross-compile):

```bash
cd engine && python -m pip install -r requirements.txt -r requirements-test.txt
node build_engine.js                      # -> engine/dist/dgm-engine/
cd ../app && npm install
npm run dist:win                          # Windows: app/dist/*.exe (installer + portable)
npm run dist:linux                        # Linux: app/dist/*.AppImage
```

**Windows build via GitHub Actions.** `.github/workflows/build.yml` runs the engine tests,
builds the engine with PyInstaller on `windows-latest`, runs the app tests, and builds the
installer and portable `.exe`, which is uploaded as a workflow artifact.

## Tests

- `engine/tests/test_engine.py` – synthetic EPSG:31258 GeoTIFFs: seams between tiles, bounds
  clipping, NoData handling, Z values equal to raster values, contour layers and exact levels,
  contour interpolation positions, TIN face counts, DXF readability (read back with `ezdxf`),
  README and ZIP contents, rejection of `dom_` files, wrong CRS, misaligned and mismatched tiles,
  partial coverage (no zero-filling), area limit, and cancel cleanup (no partial output).
- `engine/tests/test_cli.py` – the JSON contract used by the app, including coverage checks.
- `app/test/validation.test.js` – path, bounding box, prefix and job-folder validation, and engine
  command resolution.
- Real-world: `DGM_REAL_TILE_DIR=<folder> pytest -k real` runs every `dgm_*.tif` in the folder and
  checks that the point count equals the number of valid cells.

## Limitations

- DXF files are not opened in AutoCAD or Civil 3D by this project's tests. They are checked with
  an independent DXF reader (`ezdxf`) and follow the R12 layout. Please verify the output in your
  own Civil 3D installation before relying on it.
- The TIN is a regular-grid triangulation, not a surface optimised for minimum triangles.
- Contours are linear interpolations of 1 m cells; they do not model breaklines or smoothing.
- Very large areas need a bounding box split (see the cell limit) and produce very large files.
