# Data, tools and references

Every external resource this project uses. Kept current as the project grows.

## NASA data and services

| Resource | Used for | Link |
|---|---|---|
| NISAR L2 GCOV (Geocoded Polarimetric Covariance), provisional, validated and beta collections | Backscatter values for change and time-series analysis | https://nisar-docs.asf.alaska.edu/ |
| NISAR L2 GUNW (Geocoded Unwrapped Interferogram) | Line-of-sight ground displacement | https://nisar-docs.asf.alaska.edu/ |
| NISAR L3 SME2 (Soil Moisture) | Listed in coverage results | https://nisar-docs.asf.alaska.edu/ |
| Alaska Satellite Facility DAAC (NASA Earthdata) | Archive and distribution of all NISAR products | https://asf.alaska.edu/ |
| NASA Common Metadata Repository (CMR) | Granule search | https://cmr.earthdata.nasa.gov/ |
| NASA Earthdata Login | Authentication for data access | https://urs.earthdata.nasa.gov/ |
| NASA GIBS, layer `NISAR_L2_Geocoded_Polarimetric_Covariance` | Quick-look imagery on the map (not used for measurement) | https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api |
| NISAR Data User Guide (ASF) | Product structure and access patterns | https://nisar-docs.asf.alaska.edu/ |

NISAR is a joint mission of NASA and the Indian Space Research Organisation (ISRO).

## Other data

| Resource | Used for | Link |
|---|---|---|
| USGS Earthquake Catalog (FDSN event service) | Context evidence: earthquakes near an area | https://earthquake.usgs.gov/fdsnws/event/1/ |
| Water Survey of Canada real-time hydrometric data, Environment and Climate Change Canada | Context evidence and validation: river and lake levels | https://wateroffice.ec.gc.ca/ |
| USGS National Water Information System, daily values | Context evidence: gauge height in the United States | https://waterdata.usgs.gov/ |

## Software

| Library | Licence | Used for |
|---|---|---|
| h5py / HDF5 | BSD-3-Clause | Reading NISAR HDF5 granules |
| NumPy, SciPy | BSD-3-Clause | Array processing |
| pyproj / PROJ | MIT | Coordinate transforms |
| Pillow | MIT-CMU | PNG and GeoTIFF output |
| Requests | Apache-2.0 | HTTP range requests |
| FastAPI, Uvicorn, Pydantic | MIT / BSD-3-Clause | HTTP API and data contract |
| Anthropic Python SDK | MIT | Language-model calls for the investigator |

Web interface libraries are listed in `web/package.json`.

## AI use

Built with an AI coding agent (Claude Code) under the developer's direction. In the running application a
language model (Claude) plans analyses and writes the report; it does not produce numbers. A server-side
check rejects any report whose figures cannot be traced to a computed result.
