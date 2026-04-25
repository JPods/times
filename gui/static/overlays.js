/**
 * overlays.js — External data overlays
 *
 * AADT (Annual Average Daily Traffic) — FHWA/state DOT sources
 * Accident data — NHTSA / state crash data portals
 * Cell mobility — travel pattern heatmap
 *
 * Each overlay is a toggleable Leaflet layer.
 * When first toggled on, data is fetched from the server
 * (which proxies government sources) or loaded from local GeoJSON.
 *
 * Colors follow a standard gradient:
 *   AADT:     low (blue) → high (red)
 *   Accident: low (yellow) → high (red)
 *   Mobility: low (transparent) → high (orange/red) heatmap
 */

"use strict";

const Overlays = (() => {

  const _layers = {
    aadt:     null,
    accident: null,
    mobility: null,
  };

  const _active = {
    aadt:     false,
    accident: false,
    mobility: false,
  };

  // ── AADT ────────────────────────────────────────────────────────────────────

  async function _loadAADT() {
    // Fetch from server — server proxies FHWA HPMS or state DOT API
    // Falls back to a local GeoJSON file if no API key configured.
    const r = await fetch("/api/overlays/aadt");
    if (!r.ok) {
      _showOverlayNote("aadt", "AADT data not configured. See overlays/README.md.");
      return null;
    }
    const geojson = await r.json();
    return L.geoJSON(geojson, {
      style: (f) => ({
        color: _aadtColor(f.properties.aadt || 0),
        weight: 3 + Math.min(f.properties.aadt / 10000, 5),
        opacity: 0.75,
      }),
      onEachFeature: (f, layer) => {
        layer.bindTooltip(
          `${f.properties.route_name || "Road"}<br>AADT: ${(f.properties.aadt || 0).toLocaleString()}/day`,
          { sticky: true }
        );
      },
    });
  }

  function _aadtColor(aadt) {
    // Blue (low) → yellow → red (high), log scale
    const t = Math.min(Math.log10(Math.max(aadt, 1)) / 5, 1); // log10(100000) = 5
    const h = Math.round((1 - t) * 240); // 240° blue → 0° red
    return `hsl(${h},90%,50%)`;
  }

  // ── Accident data ────────────────────────────────────────────────────────────

  async function _loadAccidents() {
    const r = await fetch("/api/overlays/accidents");
    if (!r.ok) {
      _showOverlayNote("accident", "Accident data not configured. See overlays/README.md.");
      return null;
    }
    const geojson = await r.json();
    return L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => {
        const severity = f.properties.severity || 1;
        return L.circleMarker(latlng, {
          radius: 3 + severity,
          color: _severityColor(severity),
          fillColor: _severityColor(severity),
          fillOpacity: 0.6,
          weight: 1,
        });
      },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(
          `Severity: ${f.properties.severity || "?"}<br>
           ${f.properties.date || ""}<br>
           ${f.properties.description || ""}`,
          { sticky: true }
        );
      },
    });
  }

  function _severityColor(s) {
    // 1=minor (yellow), 2=serious (orange), 3=fatal (red)
    const colors = ["#f1c40f", "#e67e22", "#e74c3c"];
    return colors[Math.min(Math.round(s) - 1, 2)] || "#aaa";
  }

  // ── Cell mobility ─────────────────────────────────────────────────────────────

  async function _loadMobility() {
    const r = await fetch("/api/overlays/mobility");
    if (!r.ok) {
      _showOverlayNote("mobility", "Mobility data not configured. See overlays/README.md.");
      return null;
    }
    const geojson = await r.json();

    // Render as weighted circles (heatmap-style without plugin dependency)
    return L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => {
        const vol = f.properties.volume || 1;
        const maxVol = 1000; // normalise
        const ratio = Math.min(vol / maxVol, 1);
        return L.circleMarker(latlng, {
          radius: 4 + ratio * 16,
          color: "transparent",
          fillColor: _mobilityColor(ratio),
          fillOpacity: 0.35,
          weight: 0,
        });
      },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(
          `Cell trips/day: ${(f.properties.volume || 0).toLocaleString()}`,
          { sticky: true }
        );
      },
    });
  }

  function _mobilityColor(ratio) {
    // transparent → orange → red
    const h = Math.round(30 - ratio * 30);
    return `hsl(${h},100%,50%)`;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function _showOverlayNote(key, msg) {
    setStatus(msg);
    console.warn(`[Overlay:${key}]`, msg);
  }

  async function _toggle(key, loader) {
    const m = App.getMap();
    if (_active[key]) {
      if (_layers[key]) m.removeLayer(_layers[key]);
      _layers[key] = null;
      _active[key] = false;
      setStatus(`${key} overlay off`);
      return;
    }
    setStatus(`Loading ${key} overlay…`);
    const layer = await loader();
    if (layer) {
      layer.addTo(m);
      _layers[key] = layer;
      _active[key] = true;
      setStatus(`${key} overlay on`);
    }
  }

  return {
    toggleAADT()     { _toggle("aadt",     _loadAADT);     },
    toggleAccident() { _toggle("accident", _loadAccidents); },
    toggleMobility() { _toggle("mobility", _loadMobility);  },
  };

})();
