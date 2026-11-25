using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Kagis.Core;
using Newtonsoft.Json.Linq;
using Xunit;

namespace Kagis.Core.Tests
{
    public class ConfigTests
    {
        [Fact]
        public void Config_matches_the_engine_job_format()
        {
            var cfg = new EngineConfig
            {
                Tiles = new[] { @"C:\cache\dgm_5217-5302b.tif" },
                ContourInterval = 1.0,
                MajorInterval = 5.0,
                OutputDir = @"C:\out",
            };
            var json = cfg.ToJson();
            Assert.Equal("contours", json["outputs"][0].Value<string>());
            Assert.Equal("KAGIS", json["prefix"].Value<string>());
            Assert.False(json["make_zip"].Value<bool>());
            Assert.Equal(JTokenType.Null, json["bbox"].Type);
            Assert.Equal(5.0, json["major_interval"].Value<double>());
        }

        [Fact]
        public void Config_rejects_a_major_interval_that_is_not_a_multiple()
        {
            var cfg = new EngineConfig { Tiles = new[] { "a.tif" }, ContourInterval = 2.0, MajorInterval = 5.0, OutputDir = "x" };
            Assert.Throws<ArgumentException>(() => cfg.ToJson());
        }

        [Fact]
        public void Config_rejects_missing_tiles_or_output_folder()
        {
            Assert.Throws<ArgumentException>(() => new EngineConfig { OutputDir = "x" }.ToJson());
            Assert.Throws<ArgumentException>(() => new EngineConfig { Tiles = new[] { "a.tif" } }.ToJson());
        }
    }

    public class EngineRunnerTests : IDisposable
    {
        private readonly string _dir = Path.Combine(Path.GetTempPath(), "kagis-engine-" + Guid.NewGuid().ToString("N"));

        public void Dispose()
        {
            if (Directory.Exists(_dir)) Directory.Delete(_dir, true);
        }

        /// <summary>Python is needed to run the fake engine. Tests return early when it is not installed.</summary>
        private static string PythonOrNull()
        {
            var env = Environment.GetEnvironmentVariable("DGM_TEST_PYTHON");
            var candidates = new[] { env, "python3", "python" };
            foreach (var c in candidates.Where(c => !string.IsNullOrEmpty(c)))
            {
                try
                {
                    var psi = new System.Diagnostics.ProcessStartInfo(c, "--version")
                    { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
                    using (var p = System.Diagnostics.Process.Start(psi))
                    {
                        p.WaitForExit(10000);
                        if (p.ExitCode == 0) return c;
                    }
                }
                catch (System.ComponentModel.Win32Exception) { }
            }
            return null;
        }

        private EngineRunner Runner(string python) =>
            new EngineRunner(python, Path.Combine(AppContext.BaseDirectory, "Fixtures", "fake_engine.py"));

        private EngineConfig Config()
        {
            var tile = Path.Combine(_dir, "dgm_5217-5302b.tif");
            Directory.CreateDirectory(_dir);
            File.WriteAllBytes(tile, FakeHandler.TiffBytes());
            return new EngineConfig { Tiles = new[] { tile }, OutputDir = _dir, Prefix = "KAGIS" };
        }

        [Fact]
        public async Task Successful_run_reports_progress_warnings_and_the_contour_file()
        {
            var python = PythonOrNull();
            if (python == null) return; // no Python on this machine

            var progress = new System.Collections.Generic.List<string>();
            var result = await Runner(python).RunAsync(Config(), _dir, progress.Add, CancellationToken.None);

            Assert.True(result.Success, result.Message);
            Assert.Equal(42, result.ContourCount);
            Assert.EndsWith("KAGIS_Hoehenlinien.dxf", result.ContourFile);
            Assert.Contains("Reading DGM tiles", progress);
            Assert.Contains("test warning", result.Warnings);
            Assert.True(File.Exists(result.ContourFile));
        }

        [Fact]
        public async Task Engine_error_event_becomes_a_failed_result()
        {
            var python = PythonOrNull();
            if (python == null) return;
            Environment.SetEnvironmentVariable("FAKE_ENGINE_MODE", "error");
            try
            {
                var result = await Runner(python).RunAsync(Config(), _dir, _ => { }, CancellationToken.None);
                Assert.False(result.Success);
                Assert.Contains("No DGM cells", result.Message);
            }
            finally
            {
                Environment.SetEnvironmentVariable("FAKE_ENGINE_MODE", null);
            }
        }

        [Fact]
        public async Task Crash_without_events_reports_the_exit_code()
        {
            var python = PythonOrNull();
            if (python == null) return;
            Environment.SetEnvironmentVariable("FAKE_ENGINE_MODE", "crash");
            try
            {
                var result = await Runner(python).RunAsync(Config(), _dir, _ => { }, CancellationToken.None);
                Assert.False(result.Success);
                Assert.Contains("exit code 1", result.Message);
            }
            finally
            {
                Environment.SetEnvironmentVariable("FAKE_ENGINE_MODE", null);
            }
        }

        /// <summary>
        /// Runs the real dgm-engine on a real DGM tile. Set DGM_TEST_PYTHON (interpreter with the engine
        /// requirements installed), DGM_TEST_ENGINE_DIR (the engine folder) and DGM_TEST_TILE (a dgm_*.tif).
        /// Skipped when they are not set.
        /// </summary>
        [Fact]
        public async Task Real_engine_converts_a_real_tile_when_configured()
        {
            var python = Environment.GetEnvironmentVariable("DGM_TEST_PYTHON");
            var engineDir = Environment.GetEnvironmentVariable("DGM_TEST_ENGINE_DIR");
            var tile = Environment.GetEnvironmentVariable("DGM_TEST_TILE");
            if (string.IsNullOrEmpty(python) || string.IsNullOrEmpty(engineDir) || string.IsNullOrEmpty(tile)) return;

            Environment.SetEnvironmentVariable("PYTHONPATH", engineDir);
            try
            {
                Directory.CreateDirectory(_dir);
                var cfg = new EngineConfig { Tiles = new[] { tile }, OutputDir = _dir, Prefix = "KAGIS" };
                var result = await new EngineRunner(python, "-m", "dgm_engine")
                    .RunAsync(cfg, _dir, _ => { }, CancellationToken.None);

                Assert.True(result.Success, result.Message);
                Assert.True(result.ContourCount > 0);
                Assert.True(new FileInfo(result.ContourFile).Length > 1000);
            }
            finally
            {
                Environment.SetEnvironmentVariable("PYTHONPATH", null);
            }
        }

        [Fact]
        public async Task Missing_engine_executable_throws()
        {
            await Assert.ThrowsAnyAsync<Exception>(() =>
                new EngineRunner(Path.Combine(_dir, "no-such-engine.exe"))
                    .RunAsync(Config(), _dir, _ => { }, CancellationToken.None));
        }
    }
}
