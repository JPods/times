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
  let _radius = 10;      // default overlay radius in miles
  let _tooltipsOn = false; // overlay tooltips default off

  /** Build query string with map center + radius for spatial filtering. */
  function _spatialParams() {
    const m = App.getMap();
    if (!m) return "";
    const c = m.getCenter();
    return `?lat=${c.lat.toFixed(5)}&lon=${c.lng.toFixed(5)}&radius=${_radius}`;
  }

  // ── AADT ────────────────────────────────────────────────────────────────────

  async function _ensureAADTData() {
    if (_aadtData) return _aadtData;
    const r = await fetch("/api/overlays/aadt" + _spatialParams());
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
    const r = await fetch("/api/overlays/accidents" + _spatialParams());
    if (!r.ok) {
      _showOverlayNote("accident", "No fatal crash data for this area yet. Data will be available after Noelle processes this location.");
      return null;
    }
    const geojson = await r.json();
    // Update Morgantown comparison with fatal data
    if (geojson.features && geojson.features.length) {
      let totalFatal = 0;
      for (const f of geojson.features) totalFatal += f.properties.fatals || 1;
      const el = document.getElementById("ov-morgantown");
      if (el) {
        document.getElementById("ov-mort-fatal").textContent = totalFatal.toLocaleString();
        // Only set crash count if All Crashes hasn't set it yet
        const crashEl = document.getElementById("ov-mort-crashes");
        if (crashEl && (crashEl.textContent === "—" || crashEl.textContent === "")) {
          crashEl.textContent = "— (toggle All Crashes)";
        }
        const cityEl = document.getElementById("ov-mort-city");
        const cityLabel = document.getElementById("overlay-city-label");
        if (cityEl && cityLabel && cityLabel.textContent) {
          cityEl.textContent = cityLabel.textContent.split(",")[0];
        }
        el.style.display = "block";
      }
    }
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

  let _crashData = null;     // cached raw GeoJSON
  let _crashThreshold = 0;   // minimum crashes to render (0 = show all)

  async function _loadCrashDensity() {
    const r = await fetch("/api/overlays/crash_density" + _spatialParams());
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      _showOverlayNote("crash_density", err.error || "All-severity crash data not available for this state. Click Fetch Data first.");
      return null;
    }
    _crashData = await r.json();
    if (!_crashData.features || _crashData.features.length === 0) {
      _showOverlayNote("crash_density", "Crash data file is empty — click Fetch Data to reload.");
      return null;
    }
    // Compute percentiles for the threshold slider
    const counts = _crashData.features.map(f => f.properties.crashes).sort((a,b) => a - b);
    const p90 = counts[Math.floor(counts.length * 0.90)] || 1;
    const max = counts[counts.length - 1] || 1;
    _updateThresholdSlider(0, max, p90, counts.length);
    // Update Morgantown comparison
    _updateMorgantown(_crashData);
    return _buildCrashLayer();
  }

  function _buildCrashLayer() {
    if (!_crashData) return null;
    const filtered = {
      type: "FeatureCollection",
      features: _crashData.features.filter(f => f.properties.crashes >= _crashThreshold),
    };
    if (filtered.features.length === 0) return null;

    let maxCrashes = 1;
    for (const f of filtered.features) {
      if (f.properties.crashes > maxCrashes) maxCrashes = f.properties.crashes;
    }
    // Update the count display
    const countEl = document.getElementById("ov-threshold-count");
    if (countEl) countEl.textContent = `${filtered.features.length} / ${_crashData.features.length} cells`;

    return L.geoJSON(filtered, {
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
        const road = p.road ? `<br>${p.road}` : "";
        const type = p.top_type ? ` · ${p.top_type}` : "";
        layer.bindTooltip(
          `<b>${p.crashes} crashes</b> (${p.density}/yr)${type}<br>` +
          `${p.injury} injury, ${p.fatal} fatal<br>` +
          `${p.pedestrian} ped, ${p.bicycle || 0} bike${road}`,
          { sticky: true }
        );
      },
    });
  }

  function _updateMorgantown(geojson) {
    const el = document.getElementById("ov-morgantown");
    if (!el) return;
    let totalCrashes = 0, totalFatal = 0;
    for (const f of geojson.features) {
      totalCrashes += f.properties.crashes || 0;
      totalFatal += f.properties.fatal || 0;
    }
    // Use metadata total_raw if available (more accurate than grid sum)
    if (geojson.metadata && geojson.metadata.total_raw) {
      totalCrashes = geojson.metadata.total_raw;
    }
    document.getElementById("ov-mort-crashes").textContent = totalCrashes.toLocaleString();
    document.getElementById("ov-mort-fatal").textContent = totalFatal.toLocaleString();
    const cityEl = document.getElementById("ov-mort-city");
    const cityLabel = document.getElementById("overlay-city-label");
    if (cityEl && cityLabel && cityLabel.textContent) {
      cityEl.textContent = cityLabel.textContent.split(",")[0];
    }
    el.style.display = "block";
  }

  function _updateThresholdSlider(min, max, p90, total) {
    const slider = document.getElementById("ov-crash-threshold");
    if (!slider) return;
    slider.min = min;
    slider.max = max;
    slider.style.display = "block";
    // Show the threshold controls
    const row = document.getElementById("ov-threshold-row");
    if (row) row.style.display = "flex";
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

  const _loading = {};  // guard against double-click re-entry

  async function _toggle(key, loader, forceReload) {
    console.log(`[Overlay] toggle ${key}, active=${_active[key]}, loading=${!!_loading[key]}, force=${!!forceReload}`);
    if (_loading[key]) { console.log(`[Overlay] ${key} already loading — skip`); return; }
    const m = App.getMap();
    if (_active[key] && !forceReload) {
      if (_layers[key]) m.removeLayer(_layers[key]);
      _layers[key] = null;
      _active[key] = false;
      console.log(`[Overlay] ${key} toggled OFF`);
      setStatus(`${key} overlay off`);
      return;
    }
    // Remove old layer first (force reload or fresh load)
    if (_layers[key]) {
      m.removeLayer(_layers[key]);
      _layers[key] = null;
    }
    _loading[key] = true;
    // Latch the button immediately — show loading state with text feedback
    _active[key] = true;
    const btn = document.getElementById("ov-btn-" + key);
    const btnOrigText = btn ? btn.textContent : "";
    if (btn) {
      btn.classList.add("ov-active");
      btn.textContent = btnOrigText + " — loading";
    }
    setStatus(forceReload ? `Reloading ${key}…` : `Loading ${key}…`);
    if (typeof App !== "undefined" && App.flash) App.flash("Gathering data…", 2000);
    try {
      console.log(`[Overlay] ${key} fetching...`);
      const layer = await loader();
      console.log(`[Overlay] ${key} loader returned: ${layer ? 'layer OK' : 'NULL'}`);
      if (layer) {
        layer.addTo(m);
        _layers[key] = layer;
        _active[key] = true;
        // Default non-interactive — toggle with Tooltips button
        if (!_tooltipsOn) {
          layer.eachLayer(l => {
            if (l.getElement) { const el = l.getElement(); if (el) el.style.pointerEvents = "none"; }
            else if (l._path) l._path.style.pointerEvents = "none";
          });
        }
        if (btn) btn.textContent = btnOrigText;
        console.log(`[Overlay] ${key} toggled ON`);
        setStatus(`${key} overlay on`);
      } else {
        console.log(`[Overlay] ${key} loader returned null — data missing`);
        _active[key] = false;
        if (btn) { btn.classList.remove("ov-active"); btn.textContent = btnOrigText; }
      }
    } catch (err) {
      console.error(`[Overlay] ${key} error:`, err);
      _active[key] = false;
      if (btn) { btn.classList.remove("ov-active"); btn.textContent = btnOrigText; }
      setStatus(`${key} failed: ${err.message}`);
    } finally {
      _loading[key] = false;
    }
  }

  return {
    toggleAADT(tier, forceReload) {
      tier = tier || "core";
      const key = "aadt_" + tier;
      const m = App.getMap();
      if (_active[key] && !forceReload) {
        if (_layers[key]) m.removeLayer(_layers[key]);
        _layers[key] = null;
        _active[key] = false;
        setStatus(`Traffic ${tier} overlay off`);
        return;
      }
      if (_active[key] && _layers[key]) { m.removeLayer(_layers[key]); _layers[key] = null; }
      if (forceReload) _aadtData = null;  // clear cache to force re-fetch from current center
      (async () => {
        setStatus(forceReload ? `Reloading traffic ${tier}…` : `Loading traffic ${tier}…`);
        await _ensureAADTData();
        const layer = _buildAADTLayer(tier);
        if (layer) {
          layer.addTo(m);
          _layers[key] = layer;
          _active[key] = true;
          setStatus(`Traffic ${tier} overlay on${forceReload ? ' (reloaded)' : ''}`);
        }
      })();
    },
    toggleAccident(f) { _toggle("accident", _loadAccidents, f); },
    toggleCrashDensity(f) { _toggle("crash_density", _loadCrashDensity, f); },
    toggleMobility(f) { _toggle("mobility", _loadMobility, f); },
    togglePopDensity(f) { _toggle("pop_density", _loadPopDensity, f); },
    togglePropertyValues(f) { _toggle("property_values", _loadPropertyValues, f); },
    toggleJobs(f) { _toggle("jobs", _loadJobs, f); },

    /** Toggle overlay tooltips on/off. Default is off. */
    toggleTooltips() {
      _tooltipsOn = !_tooltipsOn;
      this.setInteractive(_tooltipsOn);
      const btn = document.getElementById("ov-btn-tooltips");
      if (btn) btn.textContent = _tooltipsOn ? "Tooltips: On" : "Tooltips: Off";
    },

    /** Disable/enable mouse interaction on all overlay layers. */
    setInteractive(enabled) {
      for (const layer of Object.values(_layers)) {
        if (!layer) continue;
        layer.eachLayer(l => {
          if (l.getElement) {
            const el = l.getElement();
            if (el) el.style.pointerEvents = enabled ? "auto" : "none";
          } else if (l._path) {
            l._path.style.pointerEvents = enabled ? "auto" : "none";
          }
        });
      }
    },

    /** Remove all overlay layers and reset state. Called on city switch / new network. */
    clearAll() {
      const m = App.getMap();
      for (const [key, layer] of Object.entries(_layers)) {
        if (layer) m.removeLayer(layer);
        _layers[key] = null;
        _active[key] = false;
      }
      _aadtData = null;
      _crashData = null;
      // Re-disable overlay buttons
      document.querySelectorAll(".ov-btn[id^='ov-btn-']").forEach(btn => {
        if (btn.id === "ov-btn-fetch" || btn.id === "ov-btn-coverage") return;
        btn.classList.add("ov-disabled");
      });
      document.querySelectorAll(".ov-signal").forEach(el => el.style.display = "none");
      const thresholdRow = document.getElementById("ov-threshold-row");
      if (thresholdRow) thresholdRow.style.display = "none";
      // Reset Fetch Data button
      const fetchBtn = document.getElementById("ov-btn-fetch");
      if (fetchBtn) {
        fetchBtn.classList.remove("fetch-done", "fetch-loading");
        fetchBtn.classList.add("fetch-needed");
        fetchBtn.innerHTML = "&#8681; Fetch Data";
      }
      const fetchStatus = document.getElementById("overlay-fetch-status");
      if (fetchStatus) fetchStatus.textContent = "";
      const morg = document.getElementById("ov-morgantown");
      if (morg) morg.style.display = "none";
    },

    /** Set the overlay radius (miles). Clears cached data so next toggle re-fetches. */
    setRadius(miles) {
      _radius = Math.max(1, Math.min(miles, 100));
      _aadtData = null;
      console.log(`[Overlay] radius set to ${_radius} miles`);
    },
    getRadius() { return _radius; },

    /** Set crash threshold — re-renders the crash density layer without re-fetching. */
    setCrashThreshold(val) {
      _crashThreshold = val;
      if (!_active.crash_density || !_crashData) return;
      const m = App.getMap();
      if (_layers.crash_density) m.removeLayer(_layers.crash_density);
      const layer = _buildCrashLayer();
      if (layer) {
        layer.addTo(m);
        _layers.crash_density = layer;
      }
    },

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
