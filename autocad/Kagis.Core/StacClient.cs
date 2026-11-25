using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace Kagis.Core
{
    /// <summary>
    /// Queries the public KAGIS STAC catalogue (https://gis.ktn.gv.at/api/stac/v1/) for
    /// DGM terrain tiles. Only the "dgm_" assets are returned; the "dom_" surface tiles that are
    /// published in the same items are ignored.
    /// </summary>
    public sealed class StacClient
    {
        public const string SearchUrl = "https://gis.ktn.gv.at/api/stac/v1/search";
        public const string Collection = "KAGIS_coll_ALS1";
        public const int MaxItems = 500;

        private readonly HttpClient _http;

        public StacClient(HttpMessageHandler handler = null)
        {
            _http = handler == null ? new HttpClient() : new HttpClient(handler);
            _http.Timeout = TimeSpan.FromMinutes(2);
        }

        /// <summary>Builds the STAC search body for a WGS 84 box.</summary>
        public static string BuildSearchBody(GeoBox box)
        {
            var body = new JObject
            {
                ["collections"] = new JArray(Collection),
                ["bbox"] = new JArray(box.ToStacBbox().Select(v => (JToken)v)),
                ["limit"] = MaxItems,
            };
            return body.ToString(Newtonsoft.Json.Formatting.None);
        }

        public async Task<IReadOnlyList<DgmTile>> SearchAsync(GeoBox box, CancellationToken ct)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Post, SearchUrl))
            {
                request.Content = new StringContent(BuildSearchBody(box), Encoding.UTF8, "application/json");
                request.Headers.Accept.ParseAdd("application/geo+json");
                using (var response = await _http.SendAsync(request, ct).ConfigureAwait(false))
                {
                    response.EnsureSuccessStatusCode();
                    var json = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    return StacParser.ParseDgmTiles(json);
                }
            }
        }

        /// <summary>Exposed for the downloader, which uses the same handler.</summary>
        public HttpClient Http => _http;
    }

    public static class StacParser
    {
        /// <summary>
        /// Reads a STAC item-search response and returns the DGM GeoTIFF of every item.
        /// Items without a DGM GeoTIFF are skipped. The result is sorted by file name.
        /// </summary>
        public static IReadOnlyList<DgmTile> ParseDgmTiles(string json)
        {
            var root = JObject.Parse(json);
            var features = root["features"] as JArray ?? new JArray();
            var tiles = new List<DgmTile>();
            foreach (var feature in features.OfType<JObject>())
            {
                var assets = feature["assets"] as JObject;
                if (assets == null) continue;
                foreach (var prop in assets.Properties())
                {
                    var name = prop.Name;
                    var href = prop.Value?["href"]?.Value<string>();
                    if (!name.StartsWith("dgm_", StringComparison.OrdinalIgnoreCase)) continue;
                    if (string.IsNullOrEmpty(href) || !href.EndsWith(".tif", StringComparison.OrdinalIgnoreCase)) continue;
                    var fileName = name.EndsWith(".tif", StringComparison.OrdinalIgnoreCase) ? name : name + ".tif";
                    var id = feature["id"]?.Value<string>() ?? name;
                    if (!TileFileNames.IsValid(fileName)) continue;
                    tiles.Add(new DgmTile(id, href, fileName));
                    break;
                }
            }
            return tiles.OrderBy(t => t.FileName, StringComparer.Ordinal).ToList();
        }
    }

    /// <summary>Checks file names that are written to disk, to keep paths inside the cache folder.</summary>
    public static class TileFileNames
    {
        public static bool IsValid(string fileName)
        {
            if (string.IsNullOrEmpty(fileName)) return false;
            if (fileName.IndexOfAny(System.IO.Path.GetInvalidFileNameChars()) >= 0) return false;
            if (fileName.Contains("..") || fileName.Contains("/") || fileName.Contains("\\")) return false;
            return System.Text.RegularExpressions.Regex.IsMatch(fileName, @"^dgm_[A-Za-z0-9_\-]+\.tif$",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        }
    }
}
