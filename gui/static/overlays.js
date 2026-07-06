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
 *   Accident: single (light blue) → multiple fatal (dark blue)
 *   Mobility: low (transparent) → high (orange/red) heatmap
 */

"use strict";

const Overlays = (() => {

  const _layers = {
    aadt_core:      null,
    aadt_secondary: null,
    accident:       null,
    mobility:       null,
  };

  const _active = {
    aadt_core:      false,
    aadt_secondary: false,
    accident:       false,
    mobility:       false,
  };

  let _aadtData = null;  // cached GeoJSON

  // ── AADT ────────────────────────────────────────────────────────────────────

  async function _ensureAADTData() {
    if (_aadtData) return _aadtData;
    const r = await fetch("/api/overlays/aadt");
    if (!r.ok) {
      _showOverlayNote("aadt", "AADT data not configured. See overlays/README.md.");
      return null;
    }
    _aadtData = await r.json();
    return _aadtData;
  }

  function _buildAADTLayer(tier) {
    if (!_aadtData) return null;
    const filtered = {
      type: "FeatureCollection",
      features: _aadtData.features.filter(f => {
        const aadt = f.properties.aadt || 0;
        if (tier === "core") return aadt >= 10000;
        if (tier === "secondary") return aadt >= 5000 && aadt < 10000;
        return aadt >= 5000;  // "all"
      }),
    };
    return L.geoJSON(filtered, {
      pointToLayer: (f, latlng) => {
        const aadt = f.properties.aadt || 0;
        const radius = 8 + Math.min(aadt / 2000, 30);
        return L.circleMarker(latlng, {
          radius: radius,
          color: _aadtColor(aadt),
          fillColor: _aadtColor(aadt),
          fillOpacity: 0.35,
          weight: 0,
        });
      },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(
          `${f.properties.route_name || "Road"}<br>AADT: ${(f.properties.aadt || 0).toLocaleString()}/day`,
          { sticky: true }
        );
      },
    });
  }

  function _aadtColor(aadt) {
    // Light red (low traffic) → dark red (high traffic)
    const t = Math.min(Math.log10(Math.max(aadt, 1)) / 5, 1);
    const r = 255;
    const g = Math.round(200 * (1 - t));
    const b = Math.round(180 * (1 - t));
    return `rgb(${r},${g},${b})`;
  }

  function _aadtColorSecondary(aadt) {
    // Orange/amber for secondary corridors (5k-10k)
    const t = Math.min((aadt - 5000) / 5000, 1);
    const r = 255;
    const g = Math.round(200 - t * 60);  // 200 → 140 (amber range)
    const b = Math.round(100 - t * 60);  // 100 → 40
    return `rgb(${r},${g},${b})`;
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
        const fatals = f.properties.fatals || f.properties.severity || 1;
        const severity = Math.min(fatals, 3);
        return L.circleMarker(latlng, {
          radius: 10 + severity * 8,
          color: "transparent",
          fillColor: _severityColor(severity),
          fillOpacity: 0.5,
          weight: 0,
        });
      },
      onEachFeature: (f, layer) => {
        const p = f.properties;
        const fatals = p.fatals || p.severity || "?";
        const road = p.road || p.description || "";
        const county = p.county || "";
        const conditions = [p.weather, p.light, p.manner].filter(Boolean).join(", ");
        layer.bindTooltip(
          `<b>${road}</b>${county ? " — " + county : ""}<br>` +
          `Fatalities: ${fatals}<br>` +
          `${p.month || p.date || ""} ${p.hour ? "Hour: " + p.hour : ""}<br>` +
          `${conditions}`,
          { sticky: true }
        );
      },
    });
  }

  function _severityColor(s) {
    // 1=single (light blue), 2=serious (medium blue), 3=multiple fatal (dark blue)
    const colors = ["#2471a3", "#1a5276", "#0b2f4a"];
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
    toggleAADT(tier) {
      tier = tier || "core";
      const key = "aadt_" + tier;
      const m = App.getMap();
      if (_active[key]) {
        if (_layers[key]) m.removeLayer(_layers[key]);
        _layers[key] = null;
        _active[key] = false;
        setStatus(`Traffic ${tier} overlay off`);
        return;
      }
      (async () => {
        setStatus(`Loading traffic ${tier}…`);
        await _ensureAADTData();
        const layer = _buildAADTLayer(tier);
        if (layer) {
          layer.addTo(m);
          _layers[key] = layer;
          _active[key] = true;
          setStatus(`Traffic ${tier} overlay on`);
        }
      })();
    },
    toggleAccident() { _toggle("accident", _loadAccidents); },
    toggleMobility() { _toggle("mobility", _loadMobility);  },
  };

})();
