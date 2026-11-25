using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Kagis.Core
{
    /// <summary>
    /// Downloads DGM GeoTIFFs into a cache folder. A file that is already there and is a valid
    /// TIFF is reused. Downloads go to a ".part" file first and are renamed only when complete.
    /// </summary>
    public sealed class TileDownloader
    {
        private readonly HttpClient _http;

        public TileDownloader(HttpClient http)
        {
            _http = http ?? throw new ArgumentNullException(nameof(http));
        }

        /// <summary>Returns the full path of the local file, downloading it when needed.</summary>
        public async Task<string> EnsureTileAsync(DgmTile tile, string folder, CancellationToken ct)
        {
            if (tile == null) throw new ArgumentNullException(nameof(tile));
            if (!TileFileNames.IsValid(tile.FileName))
                throw new ArgumentException($"Unexpected tile name: {tile.FileName}");
            Directory.CreateDirectory(folder);

            var target = Path.Combine(folder, tile.FileName);
            if (File.Exists(target) && IsTiff(target)) return target;

            var part = target + ".part";
            try
            {
                using (var request = new HttpRequestMessage(HttpMethod.Get, tile.Url))
                using (var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false))
                {
                    response.EnsureSuccessStatusCode();
                    using (var source = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (var dest = File.Create(part))
                    {
                        await source.CopyToAsync(dest, 81920, ct).ConfigureAwait(false);
                    }
                }
                if (!IsTiff(part))
                    throw new InvalidDataException($"The download of {tile.FileName} is not a GeoTIFF.");
                if (File.Exists(target)) File.Delete(target);
                File.Move(part, target);
                return target;
            }
            finally
            {
                if (File.Exists(part))
                {
                    try { File.Delete(part); } catch (IOException) { /* best effort */ }
                }
            }
        }

        /// <summary>Checks the TIFF header bytes (little or big endian).</summary>
        public static bool IsTiff(string path)
        {
            using (var fs = File.OpenRead(path))
            {
                var head = new byte[4];
                if (fs.Read(head, 0, 4) != 4) return false;
                bool little = head[0] == 0x49 && head[1] == 0x49 && head[2] == 0x2A && head[3] == 0x00;
                bool big = head[0] == 0x4D && head[1] == 0x4D && head[2] == 0x00 && head[3] == 0x2A;
                return little || big;
            }
        }
    }
}
