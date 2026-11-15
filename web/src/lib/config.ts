/** Product name. It is written here and nowhere else in the interface. */
export const APP_NAME = "Aletheia";
/** Where the source code is published. */
export const REPO_URL = "https://github.com/rupokghosh/aletheia";

export const APP_TAGLINE = "Ask a question about any place on Earth and get a radar-backed answer with receipts.";

/** Areas above this size still run, but the user is warned that they are slower. */
export const LARGE_AREA_KM2 = 400;

/** OpenFreeMap: free, keyless vector tiles built from OpenStreetMap. "positron" is its light grey style. */
export const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

/** Photon: free geocoder run by komoot on OpenStreetMap data. */
export const GEOCODER_URL = "https://photon.komoot.io/api/";

/** NASA GIBS quick-look imagery of NISAR backscatter. Context only, never measured from. */
export const GIBS = {
  wmsUrl: "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi",
  layer: "NISAR_L2_Geocoded_Polarimetric_Covariance",
  firstDate: "2025-10-29",
  label: "Radar picture of the Earth",
} as const;

/** Static index of precomputed investigations, served from web/public/showcases. */
export const SHOWCASE_INDEX_URL = "/showcases/index.json";
