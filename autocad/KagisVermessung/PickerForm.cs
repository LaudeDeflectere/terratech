using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Kagis.Core;
using Microsoft.Web.WebView2.WinForms;

namespace KagisVermessung
{
    /// <summary>
    /// Modal window with the KAGIS map (WebView2), an area box, a tile search and the conversion.
    /// It returns the path of the contour DXF; the command inserts it into the drawing.
    /// </summary>
    public sealed class PickerForm : Form
    {
        public const string BrowserUrl = "https://gis.ktn.gv.at/kagisbrowser/#/search";
        public const string WebView2Url = "https://developer.microsoft.com/microsoft-edge/webview2/";

        private readonly WebView2 _web = new WebView2();
        private readonly TextBox _area = new TextBox();
        private readonly Button _useMap = new Button();
        private readonly Button _search = new Button();
        private readonly Button _start = new Button();
        private readonly Button _cancel = new Button();
        private readonly Label _status = new Label();
        private readonly ProgressBar _progress = new ProgressBar();
        private readonly StacClient _stac = new StacClient();

        private IReadOnlyList<DgmTile> _tiles = new List<DgmTile>();
        private CancellationTokenSource _cts;
        private bool _running;

        public PickerForm()
        {
            Text = "KagisVermessung - Höhenlinien aus dem KAGIS DGM";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1100, 760);
            MinimumSize = new Size(900, 600);
            FormBorderStyle = FormBorderStyle.Sizable;
            Font = new Font("Segoe UI", 9F);

            var bottom = new TableLayoutPanel
            {
                Dock = DockStyle.Bottom,
                Height = 118,
                ColumnCount = 1,
                RowCount = 3,
                Padding = new Padding(8),
            };

            var row1 = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = false };
            row1.Controls.Add(new Label { Text = "Area (WGS 84): minLon minLat maxLon maxLat", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
            _area.Width = 360;
            _useMap.Text = "Area from map";
            _useMap.AutoSize = true;
            _search.Text = "Search tiles";
            _search.AutoSize = true;
            row1.Controls.Add(_area);
            row1.Controls.Add(_useMap);
            row1.Controls.Add(_search);

            var row2 = new FlowLayoutPanel { Dock = DockStyle.Fill };
            _start.Text = "Download and convert";
            _start.AutoSize = true;
            _start.Enabled = false;
            _cancel.Text = "Cancel";
            _cancel.AutoSize = true;
            _progress.Width = 300;
            _progress.Height = 18;
            _progress.Margin = new Padding(12, 6, 0, 0);
            row2.Controls.Add(_start);
            row2.Controls.Add(_cancel);
            row2.Controls.Add(_progress);

            _status.Dock = DockStyle.Fill;
            _status.AutoSize = false;
            _status.Text = "Pick an area on the KAGIS map, or type it above as: 14.1970 46.5870 14.2136 46.5985 - then search.";

            bottom.Controls.Add(row1, 0, 0);
            bottom.Controls.Add(row2, 0, 1);
            bottom.Controls.Add(_status, 0, 2);
            bottom.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            bottom.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            bottom.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));

            _web.Dock = DockStyle.Fill;
            Controls.Add(_web);
            Controls.Add(bottom);

            _useMap.Click += (s, e) => UseMapAddress();
            _search.Click += async (s, e) => await SearchAsync();
            _start.Click += async (s, e) => await ConvertAsync();
            _cancel.Click += (s, e) => Cancel();
            Load += async (s, e) => await InitBrowserAsync();
            FormClosing += (s, e) => { if (_running) Cancel(); };
        }

        public string ResultDxfPath { get; private set; }
        public long ResultContourCount { get; private set; }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetDllDirectory(string lpPathName);

        private async Task InitBrowserAsync()
        {
            try
            {
                // WebView2Loader.dll ships next to the plug-in; make sure Windows searches that folder.
                var pluginDir = Path.GetDirectoryName(typeof(PickerForm).Assembly.Location);
                if (!string.IsNullOrEmpty(pluginDir)) SetDllDirectory(pluginDir);

                await _web.EnsureCoreWebView2Async();
                _web.CoreWebView2.Navigate(BrowserUrl);
            }
            catch (Exception ex)
            {
                _status.Text = "The map could not be opened (WebView2 runtime missing?). " +
                               "Install the Edge WebView2 Runtime from " + WebView2Url + " or enter the area by hand. " +
                               ex.Message;
            }
        }

        private void UseMapAddress()
        {
            var url = _web.CoreWebView2?.Source;
            var box = GeoBox.TryFromUrl(url);
            if (box == null)
            {
                _status.Text = "No area was found in the map address. Enter the box by hand, then search.";
                return;
            }
            _area.Text = box.ToString();
            _status.Text = "Area taken from the map.";
        }

        private async Task SearchAsync()
        {
            GeoBox box;
            try
            {
                box = GeoBox.Parse(_area.Text);
            }
            catch (ArgumentException ex)
            {
                _status.Text = ex.Message;
                return;
            }

            SetBusy(true);
            try
            {
                _status.Text = "Searching the KAGIS catalogue...";
                _tiles = await _stac.SearchAsync(box, CancellationToken.None);
                if (_tiles.Count == 0)
                {
                    _status.Text = "No DGM tiles in this area. Choose another area.";
                    _start.Enabled = false;
                }
                else
                {
                    _status.Text = $"{_tiles.Count} DGM tiles found. Starting downloads the tiles are cached for later runs.";
                    _start.Enabled = true;
                }
            }
            catch (Exception ex)
            {
                _status.Text = "The search failed: " + ex.Message;
                _start.Enabled = false;
            }
            finally
            {
                SetBusy(false);
            }
        }

        private async Task ConvertAsync()
        {
            if (_tiles.Count == 0) return;
            var engine = EnginePath();
            if (engine == null)
            {
                _status.Text = "The conversion engine (engine\\dgm-engine.exe) was not found next to the plug-in.";
                return;
            }

            var cacheDir = Path.Combine(AppDataDir(), "Tiles");
            var outDir = Path.Combine(AppDataDir(), "Output", DateTime.Now.ToString("yyyyMMdd-HHmmss"));
            Directory.CreateDirectory(outDir);

            SetBusy(true);
            _cts = new CancellationTokenSource();
            try
            {
                var downloader = new TileDownloader(_stac.Http);
                var local = new List<string>();
                _progress.Maximum = _tiles.Count + 1;
                _progress.Value = 0;
                for (int i = 0; i < _tiles.Count; i++)
                {
                    _status.Text = $"Downloading tile {i + 1} of {_tiles.Count}: {_tiles[i].FileName}";
                    local.Add(await downloader.EnsureTileAsync(_tiles[i], cacheDir, _cts.Token));
                    _progress.Value = i + 1;
                }

                _status.Text = "Creating contours (1 m, major every 5 m)...";
                var config = new EngineConfig
                {
                    Tiles = local,
                    ContourInterval = 1.0,
                    MajorInterval = 5.0,
                    Prefix = "KAGIS",
                    OutputDir = outDir,
                };
                var result = await new EngineRunner(engine).RunAsync(config, outDir, msg => _status.Text = msg, _cts.Token);
                _progress.Value = _progress.Maximum;

                if (!result.Success)
                {
                    _status.Text = "Conversion failed: " + result.Message;
                    return;
                }

                ResultDxfPath = result.ContourFile;
                ResultContourCount = result.ContourCount;
                DialogResult = DialogResult.OK;
                Close();
            }
            catch (OperationCanceledException)
            {
                _status.Text = "Cancelled.";
            }
            catch (Exception ex)
            {
                _status.Text = "Conversion failed: " + ex.Message;
            }
            finally
            {
                _cts?.Dispose();
                _cts = null;
                SetBusy(false);
            }
        }

        private void Cancel()
        {
            _cts?.Cancel();
        }

        private void SetBusy(bool busy)
        {
            _running = busy;
            _search.Enabled = !busy;
            _useMap.Enabled = !busy;
            _area.Enabled = !busy;
            _start.Enabled = !busy && _tiles.Count > 0;
            _cancel.Enabled = busy;
            if (!busy) _progress.Value = 0;
        }

        /// <summary>
        /// The engine ships in an "engine" folder next to KagisVermessung.dll.
        /// DGM_ENGINE_EXE overrides it (for development).
        /// </summary>
        internal static string EnginePath()
        {
            var fromEnv = Environment.GetEnvironmentVariable("DGM_ENGINE_EXE");
            if (!string.IsNullOrEmpty(fromEnv) && File.Exists(fromEnv)) return fromEnv;
            var dll = typeof(PickerForm).Assembly.Location;
            var path = Path.Combine(Path.GetDirectoryName(dll) ?? "", "engine", "dgm-engine.exe");
            return File.Exists(path) ? path : null;
        }

        internal static string AppDataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "TerraTech", "KagisVermessung");
        }
    }
}
