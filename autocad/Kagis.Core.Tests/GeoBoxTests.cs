using System;
using Kagis.Core;
using Xunit;

namespace Kagis.Core.Tests
{
    public class GeoBoxTests
    {
        [Fact]
        public void Parses_space_separated_values_in_stac_order()
        {
            var box = GeoBox.Parse("14.197 46.587 14.2136 46.5985");
            Assert.Equal(new[] { 14.197, 46.587, 14.2136, 46.5985 }, box.ToStacBbox());
        }

        [Fact]
        public void Parses_comma_and_semicolon_separators()
        {
            var box = GeoBox.Parse("14.197,46.587; 14.2136,46.5985");
            Assert.Equal(14.2136, box.MaxLon, 6);
        }

        [Fact]
        public void Rejects_wrong_number_of_values()
        {
            Assert.Throws<ArgumentException>(() => GeoBox.Parse("14.1 46.5 14.2"));
        }

        [Fact]
        public void Rejects_non_numeric_values()
        {
            Assert.Throws<ArgumentException>(() => GeoBox.Parse("14.1 abc 14.2 46.6"));
        }

        [Fact]
        public void Rejects_inverted_box()
        {
            Assert.Throws<ArgumentException>(() => new GeoBox(14.3, 46.5, 14.2, 46.6));
        }

        [Fact]
        public void Rejects_values_outside_the_globe()
        {
            Assert.Throws<ArgumentException>(() => new GeoBox(14.0, 46.0, 200.0, 47.0));
        }

        [Fact]
        public void Rejects_areas_above_the_limit()
        {
            // About 0.5 degrees in each direction is roughly 2,000 km2 at this latitude.
            var ex = Assert.Throws<ArgumentException>(() => new GeoBox(13.0, 46.0, 13.5, 46.5));
            Assert.Contains("km²", ex.Message);
        }

        [Fact]
        public void Accepts_a_box_of_a_few_tiles()
        {
            var box = new GeoBox(14.197, 46.587, 14.2136, 46.5985);
            Assert.InRange(box.AreaKm2(), 0.5, 2.0);
        }

        [Fact]
        public void Finds_bbox_parameter_in_a_url_hash()
        {
            var box = GeoBox.TryFromUrl("https://gis.ktn.gv.at/kagisbrowser/#/search?bbox=14.19%2C46.58%2C14.21%2C46.60");
            Assert.NotNull(box);
            Assert.Equal(46.60, box.MaxLat, 6);
        }

        [Fact]
        public void Returns_null_when_url_has_no_usable_bbox()
        {
            Assert.Null(GeoBox.TryFromUrl("https://gis.ktn.gv.at/kagisbrowser/#/search"));
            Assert.Null(GeoBox.TryFromUrl("https://example.org/?bbox=bad"));
        }
    }
}
