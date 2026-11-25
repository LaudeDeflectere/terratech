namespace Kagis.Core
{
    /// <summary>One official KAGIS DGM (terrain) GeoTIFF offered by the STAC catalogue.</summary>
    public sealed class DgmTile
    {
        public DgmTile(string id, string url, string fileName)
        {
            Id = id;
            Url = url;
            FileName = fileName;
        }

        /// <summary>STAC item id, e.g. "5217-5302b".</summary>
        public string Id { get; }

        /// <summary>Direct download URL of the GeoTIFF.</summary>
        public string Url { get; }

        /// <summary>File name on disk, e.g. "dgm_5217-5302b.tif".</summary>
        public string FileName { get; }
    }
}
