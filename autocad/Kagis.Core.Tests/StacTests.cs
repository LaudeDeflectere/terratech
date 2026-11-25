using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Kagis.Core;
using Xunit;

namespace Kagis.Core.Tests
{
    public class StacTests
    {
        private static string Fixture(string name) =>
            File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", name));

        [Fact]
        public void Parser_returns_only_dgm_tiles_from_a_real_response()
        {
            var tiles = StacParser.ParseDgmTiles(Fixture("stac-search-villach.json"));
            Assert.Equal(2, tiles.Count);
            Assert.All(tiles, t => Assert.StartsWith("dgm_", t.FileName));
            Assert.All(tiles, t => Assert.DoesNotContain("dom_", t.FileName));
        }

        [Fact]
        public void Parser_keeps_the_download_url_and_item_id()
        {
            var tiles = StacParser.ParseDgmTiles(Fixture("stac-search-villach.json"));
            var first = tiles.First(t => t.Id == "5217-5302b");
            Assert.Equal("dgm_5217-5302b.tif", first.FileName);
            Assert.Equal("https://gis.ktn.gv.at/ogd/Hoehe/als/dgm_5217-5302b.tif", first.Url);
        }

        [Fact]
        public void Parser_skips_items_without_a_dgm_tiff()
        {
            const string json = @"{""type"":""FeatureCollection"",""features"":[
              {""id"":""x"",""assets"":{""dom_x"":{""href"":""https://h/dom_x.tif""},""dgm_x_thumbnail"":{""href"":""https://h/t.png""}}}]}";
            Assert.Empty(StacParser.ParseDgmTiles(json));
        }

        [Fact]
        public void Parser_rejects_unsafe_file_names()
        {
            const string json = @"{""features"":[{""id"":""x"",""assets"":{""dgm_../../evil"":{""href"":""https://h/evil.tif""}}}]}";
            Assert.Empty(StacParser.ParseDgmTiles(json));
        }

        [Fact]
        public void Search_body_contains_collection_bbox_and_limit()
        {
            var body = JObject.Parse(StacClient.BuildSearchBody(new GeoBox(14.197, 46.587, 14.2136, 46.5985)));
            Assert.Equal("KAGIS_coll_ALS1", body["collections"][0].Value<string>());
            Assert.Equal(14.197, body["bbox"][0].Value<double>(), 6);
            Assert.Equal(46.5985, body["bbox"][3].Value<double>(), 6);
            Assert.Equal(StacClient.MaxItems, body["limit"].Value<int>());
        }

        [Fact]
        public async Task SearchAsync_posts_to_the_catalogue_and_parses_the_answer()
        {
            var handler = new FakeHandler(_ => FakeHandler.Text(Fixture("stac-search-villach.json")));
            var client = new StacClient(handler);
            var tiles = await client.SearchAsync(new GeoBox(14.197, 46.587, 14.2136, 46.5985), CancellationToken.None);

            Assert.Equal(2, tiles.Count);
            var request = Assert.Single(handler.Requests);
            Assert.Equal(System.Net.Http.HttpMethod.Post, request.Method);
            Assert.Equal(StacClient.SearchUrl, request.RequestUri.ToString());
        }

        [Fact]
        public async Task SearchAsync_throws_on_http_error()
        {
            var handler = new FakeHandler(_ => FakeHandler.Text("{}", HttpStatusCode.InternalServerError));
            var client = new StacClient(handler);
            await Assert.ThrowsAnyAsync<Exception>(() =>
                client.SearchAsync(new GeoBox(14.197, 46.587, 14.2136, 46.5985), CancellationToken.None));
        }

    }
}
