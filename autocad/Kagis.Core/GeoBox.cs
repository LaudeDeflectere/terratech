using System;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Kagis.Core
{
    /// <summary>
    /// A rectangle in WGS 84 longitude/latitude degrees, the coordinate system used by the
    /// KAGIS STAC catalogue. Tiles are returned for every DGM tile that touches this box.
    /// </summary>
    public sealed class GeoBox
    {
        /// <summary>Upper limit for one request, in square kilometres.</summary>
        public const double MaxAreaKm2 = 25.0;

        public GeoBox(double minLon, double minLat, double maxLon, double maxLat)
        {
            MinLon = minLon;
            MinLat = minLat;
            MaxLon = maxLon;
            MaxLat = maxLat;
            Validate();
        }

        public double MinLon { get; }
        public double MinLat { get; }
        public double MaxLon { get; }
        public double MaxLat { get; }

        /// <summary>Approximate area in square kilometres (fine for the size limit check).</summary>
        public double AreaKm2()
        {
            double midLat = (MinLat + MaxLat) / 2.0 * Math.PI / 180.0;
            double heightKm = (MaxLat - MinLat) * 111.32;
            double widthKm = (MaxLon - MinLon) * 111.32 * Math.Cos(midLat);
            return heightKm * widthKm;
        }

        /// <summary>Box in the order the STAC API expects: [minLon, minLat, maxLon, maxLat].</summary>
        public double[] ToStacBbox() => new[] { MinLon, MinLat, MaxLon, MaxLat };

        public void Validate()
        {
            foreach (var v in new[] { MinLon, MinLat, MaxLon, MaxLat })
            {
                if (double.IsNaN(v) || double.IsInfinity(v))
                    throw new ArgumentException("The area contains a value that is not a number.");
            }
            if (MinLon < -180 || MaxLon > 180 || MinLat < -90 || MaxLat > 90)
                throw new ArgumentException("The area is outside the longitude/latitude range.");
            if (!(MinLon < MaxLon) || !(MinLat < MaxLat))
                throw new ArgumentException("The area needs a smaller minimum and a larger maximum in both directions.");
            if (AreaKm2() > MaxAreaKm2)
                throw new ArgumentException(
                    $"The area is {AreaKm2():0.0} km². Please choose at most {MaxAreaKm2:0} km² per conversion.");
        }

        /// <summary>
        /// Parses "minLon minLat maxLon maxLat" or "minLon,minLat,maxLon,maxLat".
        /// Values use a decimal point. Separators may be spaces, commas or semicolons.
        /// </summary>
        public static GeoBox Parse(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
                throw new ArgumentException("Enter the four values: minLon minLat maxLon maxLat.");
            var parts = Regex.Split(text.Trim(), @"[\s,;]+");
            if (parts.Length != 4)
                throw new ArgumentException("Enter exactly four values: minLon minLat maxLon maxLat.");
            var numbers = new double[4];
            for (int i = 0; i < 4; i++)
            {
                if (!double.TryParse(parts[i], NumberStyles.Float, CultureInfo.InvariantCulture, out numbers[i]))
                    throw new ArgumentException($"'{parts[i]}' is not a number.");
            }
            return new GeoBox(numbers[0], numbers[1], numbers[2], numbers[3]);
        }

        /// <summary>
        /// Looks for a "bbox=" parameter in a URL (query or hash), as the KAGIS browser may write it.
        /// Returns null when the URL does not contain a usable box.
        /// </summary>
        public static GeoBox TryFromUrl(string url)
        {
            if (string.IsNullOrEmpty(url)) return null;
            var m = Regex.Match(url, @"bbox=([^&#]+)", RegexOptions.IgnoreCase);
            if (!m.Success) return null;
            try
            {
                var value = Uri.UnescapeDataString(m.Groups[1].Value);
                return Parse(value);
            }
            catch (ArgumentException)
            {
                return null;
            }
        }

        public override string ToString() =>
            string.Format(CultureInfo.InvariantCulture, "{0:0.######} {1:0.######} {2:0.######} {3:0.######}",
                MinLon, MinLat, MaxLon, MaxLat);
    }
}
