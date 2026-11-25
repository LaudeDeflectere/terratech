# KagisVermessung for AutoCAD 2023

`KAGISVERMESSUNG` is an AutoCAD command. It shows the KAGIS map, takes the area you choose,
downloads the official DGM terrain tiles (`dgm_*.tif`) for that area, makes 1 m contours with
the TerraTech engine, and inserts the contours into the open drawing.

- Target: **AutoCAD 2023** (R23.1, .NET Framework 4.8, 64-bit, Windows).
- Data: KAGIS ALS 1 DGM, EPSG:31258. Licence CC-BY-4.0, source "KAGIS - Land Kärnten".
- Only contours (layers `HOEHENLINIEN` and `HAUPTHOEHENLINIEN`) are inserted. The orthophoto
  overlay is not part of this version.

## Install (end users)

1. Download `KagisVermessung-2023-bundle.zip` and unzip it.
2. Copy the `KagisVermessung.bundle` folder to `%APPDATA%\Autodesk\ApplicationPlugins\`.
3. Start AutoCAD 2023 and type `KAGISVERMESSUNG`.

The map needs the **Microsoft Edge WebView2 Runtime**. It is installed on most Windows 10/11 PCs.
If it is missing, the window tells you where to get it. You can also type the area by hand.

## Use

1. Pick the area on the KAGIS map, or type `minLon minLat maxLon maxLat` (WGS 84) in the box.
   "Area from map" reads the box from the map address when the map shows one.
2. **Search tiles** lists the DGM tiles that touch the area.
3. **Download and convert** downloads the tiles (they stay in the cache folder for later runs)
   and creates the contours.
4. The contours are inserted at their real coordinates. Coordinates are EPSG:31258 metres, so the
   drawing must use the same coordinate system (for example via Civil 3D coordinate systems).

Whole tiles are converted: every tile that touches the area is used, so the result can extend
slightly beyond the box you typed. Each tile is 1,250 m × 1,250 m.

Files: tiles in `%LOCALAPPDATA%\TerraTech\KagisVermessung\Tiles`, DXF output in
`%LOCALAPPDATA%\TerraTech\KagisVermessung\Output\<time>`.

## Build (developers)

Requirements: Windows, .NET SDK 8 (the plug-in itself targets .NET Framework 4.8).

```bash
dotnet test autocad/Kagis.Core.Tests -c Release           # unit tests
dotnet build autocad/KagisVermessung -c Release            # plug-in + bundle
```

The bundle is written to `autocad/KagisVermessung/bin/Release/KagisVermessung.bundle`.
It includes `Contents\engine\` when `engine/dist/dgm-engine/` exists (build it with
`node engine/build_engine.js` first). For development without a bundled engine, set
`DGM_ENGINE_EXE` to a `dgm-engine.exe` path.

The AutoCAD 2023 API comes from the Autodesk `AutoCAD.NET` 23.1.0 NuGet packages (compile-time only;
AutoCAD provides the assemblies at run time).

## Structure

```
Kagis.Core/          shared logic: area box, STAC search, tile download, engine runner (netstandard2.0)
Kagis.Core.Tests/    unit tests (xunit, net8.0), recorded STAC response, fake engine
KagisVermessung/     AutoCAD plug-in (net48): command, map window (WebView2), DXF insert
```

## Tests and what they cover

Tested on every push (`.github/workflows/autocad.yml`, Windows runner):

- Area parsing and the 25 km² limit, bbox from the map address.
- STAC: request body, and parsing of a recorded real response (only `dgm_` tiles, safe names).
- Download: TIFF check, cache reuse, rejection of HTML error pages, no partial files.
- Engine: config format, JSON events, error and crash handling.

Not tested automatically (needs Windows with AutoCAD 2023 and a display):

- Loading the plug-in in AutoCAD and running `KAGISVERMESSUNG`.
- The WebView2 map: whether "Area from map" finds a box in the map address.
- Inserting the DXF into a real drawing, and the look of the contours in Civil 3D.

Manual test checklist:

1. `NETLOAD` or bundle start: the message "KagisVermessung loaded" appears.
2. Area `14.1970 46.5870 14.2136 46.5985`, search: 8 tiles are reported.
3. Download and convert: about 1,000 contours for one tile; the contours appear in the drawing.
4. Second run for the same area: no tile is downloaded again.
5. Cancel during download: the command reports "Cancelled" and inserts nothing.
