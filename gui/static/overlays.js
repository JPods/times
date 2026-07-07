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
    crash_density:  null,
    mobility:       null,
    pop_density:    null,
    property_values:null,
    jobs:           null,
  };

  const _active = {
    aadt_core:      false,
    aadt_secondary: false,
    accident:       false,
    crash_density:  false,
    mobility:       false,
    pop_density:    false,
    property_values:false,
    jobs:           false,
  };

  let _aadtData = null;  // cached GeoJSON

  // ── AADT ────────────────────────────────────────────────────────────────────

  async function _ensureAADTData() {
    if (_aadtData) return _aadtData;
    const r = await fetch("/api/overlays/aadt");
    if (!r.ok) {
      _showOverlayNote("aadt", "No traffic data for this area yet. Save the network first, then data will be pulled for this location.");
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
      _showOverlayNote("accident", "No fatal crash data for this area yet. Data will be available after Noelle processes this location.");
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

  // ── Crash density (all severities) ──────────────────────────────────────────

  async function _loadCrashDensity() {
    const r = await fetch("/api/overlays/crash_density");
    if (!r.ok) {
      _showOverlayNote("crash_density", "No crash density data for this area yet. Data will be available after Noelle processes this location.");
      return null;
    }
    const geojson = await r.json();
    let maxCrashes = 1;
    for (const f of geojson.features) {
      if (f.properties.crashes > maxCrashes) maxCrashes = f.properties.crashes;
    }
    return L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => {
        const crashes = f.properties.crashes || 1;
        const ratio = Math.min(crashes / maxCrashes, 1);
        return L.circleMarker(latlng, {
          radius: 8 + ratio * 40,
          color: "transparent",
          fillColor: _densityColor(ratio),
          fillOpacity: 0.45,
          weight: 0,
        });
      },
      onEachFeature: (f, layer) => {
        const p = f.properties;
        layer.bindTooltip(
          `<b>${p.crashes} crashes</b> (${p.density}/yr)<br>` +
          `${p.injury} injury, ${p.fatal} fatal<br>` +
          `${p.pedestrian} pedestrian`,
          { sticky: true }
        );
      },
    });
  }

  function _densityColor(ratio) {
    // Low (light blue) → high (dark blue)
    const r = Math.round(100 * (1 - ratio));
    const g = Math.round(160 * (1 - ratio) + 40);
    const b = Math.round(180 + 75 * ratio);
    return `rgb(${r},${g},${b})`;
  }

  // ── Cell mobility ─────────────────────────────────────────────────────────────

  async function _loadMobility() {
    const r = await fetch("/api/overlays/mobility");
    if (!r.ok) {
      _showOverlayNote("mobility", "No pedestrian density data for this area yet.");
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

  // ── Census heatmaps (population, property values, jobs) ──────────────────────

  function _buildHeatLayer(geojson, colorFn, tooltipFn) {
    if (!geojson || !geojson.features || geojson.features.length === 0) return null;

    // Find max intensity for normalization
    let maxInt = 1;
    for (const f of geojson.features) {
      const v = f.properties.intensity || f.properties.value || 0;
      if (v > maxInt) maxInt = v;
    }

    return L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => {
        const val = f.properties.intensity || f.properties.value || 0;
        const ratio = Math.min(val / maxInt, 1);
        return L.circleMarker(latlng, {
          radius: 12 + ratio * 25,
          color: "transparent",
          fillColor: colorFn(ratio),
          fillOpacity: 0.4 + ratio * 0.2,
          weight: 0,
        });
      },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(tooltipFn(f.properties), { sticky: true });
      },
    });
  }

  async function _loadPopDensity() {
    console.log("[Overlay] Fetching /api/overlays/population_density...");
    const r = await fetch("/api/overlays/population_density");
    console.log("[Overlay] Response:", r.status, r.statusText);
    if (!r.ok) { console.error("[Overlay] Failed:", r.status); _showOverlayNote("pop_density", "No population data. Run: python3 scripts/census_overlays.py --all"); return null; }
    return _buildHeatLayer(await r.json(),
      (ratio) => {
        // Blue (low) → Purple (mid) → Red (high)
        const h = Math.round(240 - ratio * 240);
        return `hsl(${h}, 80%, ${55 - ratio * 15}%)`;
      },
      (p) => `<b>${p.name || "Tract"}</b><br>Pop density: ${(p.density || p.value || 0).toLocaleString()}/mi²`
    );
  }

  async function _loadPropertyValues() {
    const r = await fetch("/api/overlays/property_values");
    if (!r.ok) { _showOverlayNote("property_values", "No property value data. Run: python3 scripts/census_overlays.py --all"); return null; }
    return _buildHeatLayer(await r.json(),
      (ratio) => {
        // Green (low value) → Gold (mid) → Red (high value)
        const h = Math.round(120 - ratio * 120);
        return `hsl(${h}, 85%, ${50 - ratio * 10}%)`;
      },
      (p) => `<b>${p.name || "Tract"}</b><br>Median home value: $${(p.value || 0).toLocaleString()}`
    );
  }

  async function _loadJobs() {
    const r = await fetch("/api/overlays/jobs");
    if (!r.ok) { _showOverlayNote("jobs", "No jobs data. Run: python3 scripts/census_overlays.py --all"); return null; }
    return _buildHeatLayer(await r.json(),
      (ratio) => {
        // Cyan (low) → Blue (mid) → Dark blue (high)
        const h = Math.round(200 - ratio * 40);
        return `hsl(${h}, 90%, ${60 - ratio * 25}%)`;
      },
      (p) => `<b>${p.name || "Tract"}</b><br>Employed: ${(p.value || 0).toLocaleString()}`
    );
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function _showOverlayNote(key, msg) {
    if (typeof App !== "undefined" && App.flash) {
      App.flash(msg, 5000);
    } else {
      alert(msg);
    }
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
    toggleCrashDensity() { _toggle("crash_density", _loadCrashDensity); },
    toggleMobility() { _toggle("mobility", _loadMobility); },
    togglePopDensity() { _toggle("pop_density", _loadPopDensity); },
    togglePropertyValues() { _toggle("property_values", _loadPropertyValues); },
    toggleJobs() { _toggle("jobs", _loadJobs); },

    /** Return which overlays are currently active (for saving with .jpd). */
    getActive() {
      const result = {};
      for (const [k, v] of Object.entries(_active)) {
        if (v) result[k] = true;
      }
      return result;
    },

    /** Switch all overlays to a different city dataset. */
    async switchCity(city) {
      if (!city) return;
      // Turn off all active overlays first
      const m = App.getMap();
      for (const [k, active] of Object.entries(_active)) {
        if (active && _layers[k]) {
          m.removeLayer(_layers[k]);
          _layers[k] = null;
          _active[k] = false;
        }
      }
      _aadtData = null;  // clear cached AADT

      const r = await fetch(`/api/overlays/city/${city}`, { method: "POST" });
      if (!r.ok) {
        alert("No overlay data for city: " + city);
        return;
      }
      const result = await r.json();
      setStatus(`Overlays → ${city} (${result.switched.join(", ")})`);
    },

    /** Populate city dropdown from available datasets. */
    async loadCityList() {
      const r = await fetch("/api/overlays/cities");
      if (!r.ok) return;
      const cities = await r.json();
      const sel = document.getElementById("overlay-city");
      if (!sel) return;
      // Clear existing options after the default
      while (sel.options.length > 1) sel.remove(1);
      const labels = {
        ma: "Weymouth MA", mn: "Bloomington MN", ok: "Tulsa OK",
        nj: "Secaucus NJ", sc: "Greenville SC",
      };
      for (const city of Object.keys(cities)) {
        const opt = document.createElement("option");
        opt.value = city;
        opt.textContent = labels[city] || city.toUpperCase();
        sel.appendChild(opt);
      }
    },
  };

})();

// City list removed — using Fetch Data button instead
