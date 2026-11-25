using System;
using System.IO;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using Kagis.Core;
using Xunit;

namespace Kagis.Core.Tests
{
    public class DownloaderTests : IDisposable
    {
        private readonly string _dir = Path.Combine(Path.GetTempPath(), "kagis-tests-" + Guid.NewGuid().ToString("N"));

        public void Dispose()
        {
            if (Directory.Exists(_dir)) Directory.Delete(_dir, true);
        }

        private static DgmTile Tile(string name = "dgm_5217-5302b.tif") =>
            new DgmTile("5217-5302b", "https://gis.ktn.gv.at/ogd/Hoehe/als/" + name, name);

        [Fact]
        public async Task Downloads_a_tiff_and_renames_it_into_place()
        {
            var handler = new FakeHandler(_ => FakeHandler.Bytes(FakeHandler.TiffBytes()));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));

            var path = await downloader.EnsureTileAsync(Tile(), _dir, CancellationToken.None);

            Assert.Equal(Path.Combine(_dir, "dgm_5217-5302b.tif"), path);
            Assert.True(File.Exists(path));
            Assert.False(File.Exists(path + ".part"));
            Assert.True(TileDownloader.IsTiff(path));
        }

        [Fact]
        public async Task Reuses_a_valid_cached_file_without_a_request()
        {
            Directory.CreateDirectory(_dir);
            File.WriteAllBytes(Path.Combine(_dir, "dgm_5217-5302b.tif"), FakeHandler.TiffBytes());
            var handler = new FakeHandler(_ => throw new InvalidOperationException("no request expected"));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));

            await downloader.EnsureTileAsync(Tile(), _dir, CancellationToken.None);

            Assert.Empty(handler.Requests);
        }

        [Fact]
        public async Task Replaces_a_cached_file_that_is_not_a_tiff()
        {
            Directory.CreateDirectory(_dir);
            File.WriteAllText(Path.Combine(_dir, "dgm_5217-5302b.tif"), "<html>error</html>");
            var handler = new FakeHandler(_ => FakeHandler.Bytes(FakeHandler.TiffBytes()));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));

            var path = await downloader.EnsureTileAsync(Tile(), _dir, CancellationToken.None);

            Assert.Single(handler.Requests);
            Assert.True(TileDownloader.IsTiff(path));
        }

        [Fact]
        public async Task Rejects_a_response_that_is_not_a_tiff_and_leaves_no_file()
        {
            var handler = new FakeHandler(_ => FakeHandler.Bytes(new byte[] { 0x3C, 0x68, 0x74, 0x6D, 0x6C }));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));

            await Assert.ThrowsAsync<InvalidDataException>(() =>
                downloader.EnsureTileAsync(Tile(), _dir, CancellationToken.None));

            Assert.False(File.Exists(Path.Combine(_dir, "dgm_5217-5302b.tif")));
            Assert.False(File.Exists(Path.Combine(_dir, "dgm_5217-5302b.tif.part")));
        }

        [Fact]
        public async Task Http_errors_throw_and_leave_no_partial_file()
        {
            var handler = new FakeHandler(_ => FakeHandler.Bytes(new byte[0], HttpStatusCode.NotFound));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));

            await Assert.ThrowsAnyAsync<Exception>(() =>
                downloader.EnsureTileAsync(Tile(), _dir, CancellationToken.None));
            Assert.Empty(Directory.Exists(_dir) ? Directory.GetFiles(_dir) : new string[0]);
        }

        [Fact]
        public async Task Refuses_unexpected_file_names()
        {
            var handler = new FakeHandler(_ => FakeHandler.Bytes(FakeHandler.TiffBytes()));
            var downloader = new TileDownloader(new System.Net.Http.HttpClient(handler));
            await Assert.ThrowsAsync<ArgumentException>(() =>
                downloader.EnsureTileAsync(Tile("..\\evil.tif"), _dir, CancellationToken.None));
            Assert.Empty(handler.Requests);
        }

        [Fact]
        public void Recognises_both_byte_orders()
        {
            Directory.CreateDirectory(_dir);
            var little = Path.Combine(_dir, "l.tif");
            var big = Path.Combine(_dir, "b.tif");
            File.WriteAllBytes(little, new byte[] { 0x49, 0x49, 0x2A, 0x00 });
            File.WriteAllBytes(big, new byte[] { 0x4D, 0x4D, 0x00, 0x2A });
            Assert.True(TileDownloader.IsTiff(little));
            Assert.True(TileDownloader.IsTiff(big));
        }
    }
}
