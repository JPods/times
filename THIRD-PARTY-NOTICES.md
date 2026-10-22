# Third-Party Notices — MeshMobility

Every outside library MeshMobility uses, what it is for, and its license.
Add or remove an entry in the same commit as the dependency.

## Bundled in this repository (gui/static/)

| Library | Version | License | Purpose |
|---|---|---|---|
| [JSZip](https://stuk.github.io/jszip/) | 3.10.1 | MIT (dual MIT / GPLv3 — used under MIT) | CityKit: build .zip downloads in the browser (`jszip.min.js`) |
| [Leaflet.GeometryUtil](https://github.com/makinacorpus/Leaflet.GeometryUtil) | not stated in file | BSD-3-Clause | Distances and positions along polylines (`leaflet-geometryutil.js`) |
| [Leaflet-Arrowheads](https://github.com/slutske22/leaflet-arrowheads) | not stated in file | MIT | Direction arrows on one-way guideways (`leaflet-arrowheads.js`) |

## Loaded from CDN

| Library | Version | License | Purpose |
|---|---|---|---|
| [Leaflet](https://leafletjs.com) | 1.9.4 | BSD-2-Clause | Map |
| [Turf.js](https://turfjs.org) | 6.5.0 | MIT | Coverage unions (walk/bike reach) |
| [html2canvas](https://html2canvas.hertzen.com) | 1.4.1 | MIT | Map screenshots |
| [docx](https://docx.js.org) | 9.0.3 | MIT | CityTool: Word document export |

## Python (requirements.txt)

| Library | Version | License | Purpose |
|---|---|---|---|
| Flask | 3.1.3 | BSD-3-Clause | Web server |
| Werkzeug | 3.1.8 | BSD-3-Clause | Flask WSGI layer |
| Jinja2 | 3.1.6 | BSD-3-Clause | Flask templates |
| MarkupSafe | 3.0.3 | BSD-3-Clause | Jinja2 escaping |
| itsdangerous | 2.2.0 | BSD-3-Clause | Flask session signing |
| click | 8.4.2 | BSD-3-Clause | Flask CLI |
| blinker | 1.9.0 | MIT | Flask signals |
| packaging | 26.2 | Apache-2.0 / BSD-2-Clause | Version parsing |
| gunicorn | 26.0.0 | MIT | Production server |
| flask-session | 0.8.0 | BSD-3-Clause | Server-side sessions |
| redis | >=5.0 | MIT | Session store client |
| requests | >=2.31 | Apache-2.0 | HTTP client (overlay harvests) |

## License compatibility

No GPL or LGPL code is used. JSZip is dual-licensed; MeshMobility uses it under MIT.
