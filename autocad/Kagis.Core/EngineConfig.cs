using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace Kagis.Core
{
    /// <summary>
    /// Job settings for the bundled dgm-engine. Field names match engine/dgm_engine/job.py.
    /// The AutoCAD command only asks for contours.
    /// </summary>
    public sealed class EngineConfig
    {
        public IReadOnlyList<string> Tiles { get; set; } = new List<string>();
        public double ContourInterval { get; set; } = 1.0;
        public double MajorInterval { get; set; } = 5.0;
        public string Prefix { get; set; } = "KAGIS";
        public string OutputDir { get; set; } = "";

        public JObject ToJson()
        {
            if (Tiles == null || Tiles.Count == 0)
                throw new System.ArgumentException("No tiles were given.");
            if (!(ContourInterval > 0) || !(MajorInterval > 0))
                throw new System.ArgumentException("Contour intervals must be positive.");
            double ratio = MajorInterval / ContourInterval;
            if (System.Math.Abs(ratio - System.Math.Round(ratio)) > 1e-9 || System.Math.Round(ratio) < 1)
                throw new System.ArgumentException("The major interval must be a whole multiple of the contour interval.");
            if (string.IsNullOrEmpty(OutputDir))
                throw new System.ArgumentException("An output folder is required.");

            return new JObject
            {
                ["tiles"] = new JArray(Tiles.Select(t => (JToken)t)),
                ["bbox"] = null,                       // whole tiles that touch the chosen area
                ["outputs"] = new JArray("contours"),
                ["prefix"] = Prefix,
                ["contour_interval"] = ContourInterval,
                ["major_interval"] = MajorInterval,
                ["output_dir"] = OutputDir,
                ["make_zip"] = false,
            };
        }
    }
}
