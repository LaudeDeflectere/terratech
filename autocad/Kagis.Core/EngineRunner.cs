using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace Kagis.Core
{
    /// <summary>The final result of one engine run.</summary>
    public sealed class EngineResult
    {
        public bool Success { get; set; }
        public string Message { get; set; }
        public string ContourFile { get; set; }
        public long ContourCount { get; set; }
        public IList<string> Warnings { get; } = new List<string>();
    }

    /// <summary>
    /// Runs dgm-engine with "convert --config job.json" and reads its JSON-line events from stdout.
    /// The process is started without a shell. Cancelling kills the process and the engine
    /// removes its own incomplete job folder.
    /// </summary>
    public sealed class EngineRunner
    {
        private readonly string _fileName;
        private readonly string[] _leadingArgs;

        /// <param name="fileName">dgm-engine.exe, or python for development runs.</param>
        /// <param name="leadingArgs">Arguments placed before "convert", e.g. "-m", "dgm_engine".</param>
        public EngineRunner(string fileName, params string[] leadingArgs)
        {
            _fileName = fileName ?? throw new ArgumentNullException(nameof(fileName));
            _leadingArgs = leadingArgs ?? new string[0];
        }

        public Task<EngineResult> RunAsync(EngineConfig config, string workDir, Action<string> progress, CancellationToken ct)
        {
            return Task.Run(() => Run(config, workDir, progress, ct), ct);
        }

        private EngineResult Run(EngineConfig config, string workDir, Action<string> progress, CancellationToken ct)
        {
            Directory.CreateDirectory(workDir);
            var configPath = Path.Combine(workDir, "job-" + Guid.NewGuid().ToString("N") + ".json");
            File.WriteAllText(configPath, config.ToJson().ToString(Newtonsoft.Json.Formatting.None), new UTF8Encoding(false));

            var args = new StringBuilder();
            foreach (var a in _leadingArgs) args.Append(Quote(a)).Append(' ');
            args.Append("convert --config ").Append(Quote(configPath));

            var psi = new ProcessStartInfo(_fileName, args.ToString())
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };

            var result = new EngineResult();
            var stderr = new StringBuilder();
            string errorMessage = null;
            using (var process = Process.Start(psi))
            {
                if (process == null) throw new InvalidOperationException("The engine could not be started.");
                process.ErrorDataReceived += (s, e) => { if (e.Data != null && stderr.Length < 4000) stderr.AppendLine(e.Data); };
                process.BeginErrorReadLine();

                using (ct.Register(() => { try { if (!process.HasExited) process.Kill(); } catch (InvalidOperationException) { } }))
                {
                    string line;
                    while ((line = process.StandardOutput.ReadLine()) != null)
                    {
                        if (line.Length == 0 || line[0] != '{') continue;
                        JObject ev;
                        try { ev = JObject.Parse(line); }
                        catch (Newtonsoft.Json.JsonException) { continue; }
                        var kind = ev["event"]?.Value<string>();
                        switch (kind)
                        {
                            case "progress":
                                progress?.Invoke(ev["message"]?.Value<string>() ?? "");
                                break;
                            case "warning":
                                result.Warnings.Add(ev["message"]?.Value<string>() ?? "");
                                break;
                            case "done":
                                ReadDone(ev, result);
                                break;
                            case "error":
                                errorMessage = ev["message"]?.Value<string>() ?? "The engine reported an error.";
                                break;
                        }
                    }
                    process.WaitForExit();
                }

                ct.ThrowIfCancellationRequested();
                if (errorMessage != null)
                {
                    result.Success = false;
                    result.Message = errorMessage;
                }
                else if (process.ExitCode != 0)
                {
                    result.Success = false;
                    result.Message = $"The engine stopped with exit code {process.ExitCode}. {LastLines(stderr.ToString())}".Trim();
                }
                else
                {
                    result.Success = result.ContourFile != null;
                    if (!result.Success) result.Message = "The engine finished without writing the contour file.";
                }
            }
            try { File.Delete(configPath); } catch (IOException) { }
            return result;
        }

        /// <summary>Reads the "outputs" list of the final "done" event (see engine/dgm_engine/job.py).</summary>
        private static void ReadDone(JObject ev, EngineResult result)
        {
            var outputs = ev["outputs"] as JArray;
            if (outputs == null) return;
            foreach (var o in outputs.OfType<JObject>())
            {
                if (o["kind"]?.Value<string>() != "contours") continue;
                result.ContourFile = o["path"]?.Value<string>();
                result.ContourCount = o["counts"]?["contours"]?.Value<long?>() ?? 0;
            }
        }

        private static string LastLines(string text)
        {
            var lines = text.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
            var tail = lines.Length > 3 ? lines[lines.Length - 3] + " " + lines[lines.Length - 2] + " " + lines[lines.Length - 1] : string.Join(" ", lines);
            return tail.Trim();
        }

        private static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return arg;
            return "\"" + arg.Replace("\"", "\\\"") + "\"";
        }
    }
}
