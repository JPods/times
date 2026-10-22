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
      if (err.contact) {
        _showCrashContact(err.state, err.contact);
      } else {
        { const st = err.state || ""; const msg = err.error || "No crash data for this area."; if (err.has_partial) { _showSearchPrompt(st, msg + " Click Search to try harvesting this county."); } else { _showSearchPrompt(st, msg); } }
      }
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

  function _showCrashContact(state, contact) {
    const name = contact.contact || `${state} DOT`;
    const url = contact.contact_url || "";
    const phone = contact.contact_phone || "";
    const notes = contact.notes || "";
    const status = contact.status || "unavailable";

    let html = `<div style="max-width:420px;font-family:system-ui;line-height:1.5">`;
    html += `<div style="font-size:15px;font-weight:700;margin-bottom:8px">` +
            `No crash data for ${state}</div>`;
    html += `<div style="font-size:13px;color:#ccc;margin-bottom:10px">${notes}</div>`;
    html += `<div style="font-size:13px;margin-bottom:6px">` +
            `<b>Contact:</b> ${name}</div>`;
    if (phone) {
      html += `<div style="font-size:13px;margin-bottom:6px">` +
              `<b>Phone:</b> <a href="tel:${phone}" style="color:#5bf">${phone}</a></div>`;
    }
    if (url) {
      html += `<div style="font-size:13px;margin-bottom:10px">` +
              `<a href="${url}" target="_blank" style="color:#5bf">${url}</a></div>`;
    }
    const portal = contact.request_portal || "";
    if (portal) {
      html += `<div style="font-size:13px;margin-bottom:10px">` +
              `<b>Submit a data request:</b> <a href="${portal}" target="_blank" ` +
              `style="color:#5bf;font-weight:700">${portal}</a></div>`;
    }
    html += `<div style="font-size:12px;color:#aaa;border-top:1px solid #444;padding-top:8px;margin-top:8px">` +
            `Every state collects crash data. When you call or submit a request, ` +
            `ask for all-severity crash data with coordinates. The more people ` +
            `who ask, the faster states publish it.</div>`;
    html += `</div>`;

    // Show as a modal dialog over the map
    let overlay = document.getElementById("crash-contact-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "crash-contact-overlay";
      overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;" +
        "background:rgba(0,0,0,0.6);display:flex;align-items:center;" +
        "justify-content:center;z-index:10000";
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.remove();
      });
      document.body.appendChild(overlay);
    }
    const box = document.createElement("div");
    box.style.cssText = "background:#1a1a2e;color:#eee;padding:24px;border-radius:8px;" +
      "box-shadow:0 4px 24px rgba(0,0,0,0.5);position:relative";
    const close = document.createElement("button");
    close.textContent = "×";
    close.style.cssText = "position:absolute;top:8px;right:12px;background:none;" +
      "border:none;color:#888;font-size:20px;cursor:pointer";
    close.onclick = () => overlay.remove();
    box.appendChild(close);
    box.insertAdjacentHTML("beforeend", html);
    overlay.innerHTML = "";
    overlay.appendChild(box);

    setStatus(`No crash data for ${state} — contact info shown`);
    console.warn(`[Overlay:crash_density] Missing state ${state}:`, contact);
  }

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

  // ── Data Search Protocol — 2026-07-30 ──
  let _searchPolling = null;

  function _startDataSearch(state) {
    var sp = _spatialParams().replace("?", "").split("&");
    var slat = "", slon = "", srad = "";
    sp.forEach(function(p) {
      if (p.startsWith("lat=")) slat = p.split("=")[1];
      if (p.startsWith("lon=")) slon = p.split("=")[1];
      if (p.startsWith("radius=")) srad = p.split("=")[1];
    });
    fetch("/api/overlays/search_data", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({state: state, lat: slat, lon: slon, radius: srad || "10"}),
    })
    .then(r => r.json())
    .then(data => {
      if (data.status === "found") {
        _showSearchFound(data);
      } else {
        _showSearchProgress(state, data);
        _searchPolling = setInterval(() => _pollSearch(state), 2000);
      }
    })
    .catch(e => {
      _showOverlayNote("crash_density", "Search failed: " + e.message);
    });
  }

  function _pollSearch(state) {
    fetch("/api/overlays/search_status?state=" + state)
    .then(r => r.json())
    .then(data => {
      if (data.status === "found") {
        clearInterval(_searchPolling);
        _searchPolling = null;
        _showSearchFound(data);
      } else if (data.status === "not_found" || data.status === "cancelled") {
        clearInterval(_searchPolling);
        _searchPolling = null;
        _showSearchExhausted(data);
      } else {
        _updateSearchProgress(data);
      }
    })
    .catch(() => {});
  }

  function _showSearchPrompt(state, errorMsg) {
    let el = document.getElementById("data-search-panel");
    if (!el) {
      el = document.createElement("div");
      el.id = "data-search-panel";
      el.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);" +
        "background:#1a1a2e;color:#eee;padding:24px;border-radius:10px;" +
        "box-shadow:0 4px 24px rgba(0,0,0,0.6);z-index:10000;min-width:380px;" +
        "font-family:system-ui;line-height:1.6;max-width:500px";
      document.body.appendChild(el);
    }
    el.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
      '<span style="font-size:15px;font-weight:700">' + errorMsg + '</span>' +
      '<button onclick="document.getElementById(\'data-search-panel\').remove()"' +
      ' style="background:none;border:none;color:#888;font-size:18px;cursor:pointer">&times;</button></div>' +
      '<div style="font-size:13px;color:#aaa;margin-bottom:16px">' +
      'Know a data source? Enter a URL or agency name:</div>' +
      '<input id="ds-user-source" type="text" placeholder="e.g. https://data.ok.gov/crashes or OK DPS"' +
      ' style="width:100%;padding:8px;border-radius:4px;border:1px solid #444;' +
      'background:#0d0d1a;color:#eee;font-size:13px;margin-bottom:12px;box-sizing:border-box">' +
      '<div style="display:flex;gap:8px">' +
      '<button onclick="Overlays._startDataSearch(\'' + state + '\')"' +
      ' style="flex:1;padding:10px;border-radius:6px;border:none;' +
      'background:#1d4ed8;color:#fff;font-weight:600;cursor:pointer;font-size:13px">' +
      'Search for Data</button>' +
      '<button onclick="document.getElementById(\'data-search-panel\').remove()"' +
      ' style="padding:10px 16px;border-radius:6px;border:1px solid #444;' +
      'background:none;color:#aaa;cursor:pointer;font-size:13px">Cancel</button></div>';
    el.style.display = "block";
  }

  function _showSearchProgress(state, data) {
    let el = document.getElementById("data-search-panel");
    if (!el) return;
    el.innerHTML = '<div style="font-size:15px;font-weight:700;margin-bottom:12px">' +
      'Searching for ' + state.toUpperCase() + ' crash data...</div>' +
      '<div id="ds-progress-bar" style="background:#333;border-radius:4px;height:6px;margin-bottom:12px">' +
      '<div style="background:#1d4ed8;height:6px;border-radius:4px;width:0%;transition:width 0.3s"></div></div>' +
      '<div id="ds-progress-text" style="font-size:12px;color:#aaa">Starting search...</div>' +
      '<div id="ds-sources-list" style="font-size:11px;color:#666;margin-top:10px;max-height:120px;overflow-y:auto"></div>' +
      '<button onclick="document.getElementById(\'data-search-panel\').remove();' +
      'if(window._searchPolling){clearInterval(window._searchPolling);window._searchPolling=null;}"' +
      ' style="margin-top:12px;padding:6px 16px;border-radius:4px;border:1px solid #444;' +
      'background:none;color:#aaa;cursor:pointer;font-size:12px">Cancel</button>';
  }

  function _updateSearchProgress(data) {
    var pct = data.total > 0 ? Math.round((data.tried / data.total) * 100) : 0;
    var bar = document.querySelector("#ds-progress-bar > div");
    if (bar) bar.style.width = pct + "%";
    var txt = document.getElementById("ds-progress-text");
    if (txt) txt.textContent = "Checking: " + (data.current || "...") +
      " (" + data.tried + "/" + data.total + ") - " + Math.round(data.elapsed) + "s";
    var list = document.getElementById("ds-sources-list");
    if (list && data.sources) {
      list.innerHTML = data.sources.map(function(s) {
        var icon = s.status === "done" ? "OK" : s.status === "trying" ? ">>" :
                   s.status === "no_data" ? "--" : s.status === "pending" ? ".." : "!!";
        var color = s.status === "done" ? "#4ade80" : s.status === "trying" ? "#60a5fa" :
                    s.status.indexOf("error") === 0 ? "#ef4444" : "#666";
        return '<div style="color:' + color + '">' + icon + ' ' + s.name + '</div>';
      }).join("");
    }
  }

  function _showSearchFound(data) {
    var el = document.getElementById("data-search-panel");
    if (!el) {
      el = document.createElement("div");
      el.id = "data-search-panel";
      el.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);" +
        "background:#0a2a0a;color:#eee;padding:24px;border-radius:10px;" +
        "box-shadow:0 4px 24px rgba(0,0,0,0.6);z-index:10000;min-width:380px;" +
        "font-family:system-ui;line-height:1.6";
      document.body.appendChild(el);
    }
    el.style.background = "#0a2a0a";
    el.innerHTML = '<div style="font-size:15px;font-weight:700;color:#4ade80;margin-bottom:12px">' +
      'Data Found: ' + (data.message || "") + '</div>' +
      '<div style="font-size:13px;color:#aaa;margin-bottom:16px">' +
      (data.feature_count ? data.feature_count + " data points loaded." : "") + '</div>' +
      '<button onclick="document.getElementById(\'data-search-panel\').remove();' +
      'Overlays.toggleCrashDensity(true)"' +
      ' style="width:100%;padding:12px;border-radius:6px;border:none;' +
      'background:#16a34a;color:#fff;font-weight:700;cursor:pointer;font-size:14px">' +
      'Reload Data</button>';
  }

  function _showSearchExhausted(data) {
    var el = document.getElementById("data-search-panel");
    if (!el) return;
    el.style.background = "#1a1a2e";
    var sourcesHtml = "";
    if (data.sources && data.sources.length > 0) {
      sourcesHtml = '<div style="font-size:11px;color:#888;margin:12px 0;max-height:150px;overflow-y:auto">' +
        '<div style="font-weight:600;margin-bottom:4px">Sources checked:</div>' +
        data.sources.map(function(s) {
          var color = s.status === "done" ? "#4ade80" : s.status.indexOf("error") === 0 ? "#ef4444" : "#888";
          return '<div style="color:' + color + '">- ' + s.name + ' : ' + s.status + '</div>';
        }).join("") + '</div>';
    }
    var st = data.state || "";
    el.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
      '<span style="font-size:15px;font-weight:700;color:#ef4444">Search Complete - Data Not Found</span>' +
      '<button onclick="document.getElementById(\'data-search-panel\').remove()"' +
      ' style="background:none;border:none;color:#888;font-size:18px;cursor:pointer">&times;</button></div>' +
      '<div style="font-size:13px;color:#ccc;margin-bottom:8px">' + (data.message || "") + '</div>' +
      sourcesHtml +
      '<div style="font-size:13px;color:#aaa;margin-top:12px">Know a source? Enter URL or agency:</div>' +
      '<input id="ds-user-source" type="text" placeholder="URL or agency name"' +
      ' style="width:100%;padding:8px;border-radius:4px;border:1px solid #444;' +
      'background:#0d0d1a;color:#eee;font-size:13px;margin:8px 0;box-sizing:border-box">' +
      '<button onclick="Overlays._startDataSearch(\'' + st + '\')"' +
      ' style="width:100%;padding:10px;border-radius:6px;border:none;' +
      'background:#1d4ed8;color:#fff;font-weight:600;cursor:pointer;font-size:13px">Try Again</button>';
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
    _startDataSearch(state) { _startDataSearch(state); },
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

// ── Custom Points Overlay ─────────────────────────────────────────────────────
// Generic point overlay tool. Accepts JSON array [{lat,lon,label}] or CSV.
// Points rendered as distinct diamond markers so they don't blend with crash data.

const CustomPoints = (() => {
  let _layer = null;
  let _data = null;  // array of {lat, lon, label, ...extra properties}
  let _active = false;

  function _parseJSON(text) {
    const parsed = JSON.parse(text);
    // Handle GeoJSON FeatureCollection
    if (parsed.type === "FeatureCollection" && parsed.features) {
      return parsed.features.map(f => ({
        lat: f.geometry.coordinates[1],
        lon: f.geometry.coordinates[0],
        label: f.properties.name || f.properties.label || f.properties.stop_name || "",
        ...f.properties,
      }));
    }
    // Handle plain array
    if (Array.isArray(parsed)) return parsed;
    // Handle {points: [...]}
    if (parsed.points) return parsed.points;
    throw new Error("Unrecognized JSON format");
  }

  function _parseCSV(text) {
    const lines = text.trim().split("\n");
    if (lines.length < 2) throw new Error("CSV needs header + at least 1 row");
    const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
    const latIdx = headers.findIndex(h => h === "lat" || h === "latitude" || h === "stop_lat");
    const lonIdx = headers.findIndex(h => h === "lon" || h === "lng" || h === "longitude" || h === "stop_lon");
    const labelIdx = headers.findIndex(h => h === "label" || h === "name" || h === "stop_name" || h === "station");
    if (latIdx < 0 || lonIdx < 0) throw new Error("CSV must have lat/lon columns");
    const points = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(",").map(c => c.trim());
      const lat = parseFloat(cols[latIdx]);
      const lon = parseFloat(cols[lonIdx]);
      if (isNaN(lat) || isNaN(lon)) continue;
      points.push({ lat, lon, label: labelIdx >= 0 ? cols[labelIdx] : "" });
    }
    return points;
  }

  function _render() {
    if (!_data || _data.length === 0) return;
    const m = App.getMap();
    if (_layer) { m.removeLayer(_layer); _layer = null; }

    _layer = L.layerGroup();
    for (const pt of _data) {
      const marker = L.circleMarker([pt.lat, pt.lon], {
        radius: 7,
        color: "#fff",
        weight: 2,
        fillColor: "#f5a623",
        fillOpacity: 0.9,
      });
      const tooltip = pt.label || `${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)}`;
      marker.bindTooltip(tooltip, { sticky: true });
      _layer.addLayer(marker);
    }
    _layer.addTo(m);
    _active = true;

    const btn = document.getElementById("ov-btn-custom_points");
    if (btn) btn.classList.add("ov-active");
    const status = document.getElementById("ov-custom-status");
    if (status) status.textContent = `${_data.length} points loaded`;
    setStatus(`Custom points: ${_data.length} loaded`);
  }

  return {
    toggle() {
      const input = document.getElementById("ov-custom-input");
      if (input) input.style.display = input.style.display === "none" ? "block" : "none";
      if (_active && _layer) {
        const m = App.getMap();
        m.removeLayer(_layer);
        _layer = null;
        _active = false;
        const btn = document.getElementById("ov-btn-custom_points");
        if (btn) btn.classList.remove("ov-active");
        setStatus("Custom points off");
      } else if (_data) {
        _render();
      } else {
        // Try loading from server (saved in .jpd)
        fetch("/api/overlays/custom_points").then(r => r.json()).then(pts => {
          if (pts && pts.length) { _data = pts; _render(); }
        }).catch(() => {});
      }
    },

    loadFile() {
      document.getElementById("ov-custom-file").click();
    },

    handleFile(file) {
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const text = e.target.result;
          if (file.name.endsWith(".csv")) {
            _data = _parseCSV(text);
          } else {
            _data = _parseJSON(text);
          }
          _render();
        } catch (err) {
          const status = document.getElementById("ov-custom-status");
          if (status) status.textContent = "Error: " + err.message;
          console.error("[CustomPoints]", err);
        }
      };
      reader.readAsText(file);
    },

    fromPaste() {
      const textarea = document.getElementById("ov-custom-paste");
      if (!textarea || !textarea.value.trim()) return;
      try {
        const text = textarea.value.trim();
        // Detect CSV vs JSON
        if (text.startsWith("[") || text.startsWith("{")) {
          _data = _parseJSON(text);
        } else {
          _data = _parseCSV(text);
        }
        _render();
      } catch (err) {
        const status = document.getElementById("ov-custom-status");
        if (status) status.textContent = "Error: " + err.message;
        console.error("[CustomPoints]", err);
      }
    },

    clear() {
      const m = App.getMap();
      if (_layer) { m.removeLayer(_layer); _layer = null; }
      _data = null;
      _active = false;
      const btn = document.getElementById("ov-btn-custom_points");
      if (btn) btn.classList.remove("ov-active");
      const status = document.getElementById("ov-custom-status");
      if (status) status.textContent = "";
      const textarea = document.getElementById("ov-custom-paste");
      if (textarea) textarea.value = "";
      setStatus("Custom points cleared");
    },

    /** Get current data for saving with .jpd */
    getData() { return _data; },

    /** Load data programmatically (e.g., from .jpd restore) */
    setData(points) {
      if (!points || !points.length) return;
      _data = points;
      _render();
    },

    /** Load presets list from server */
    async loadPresets() {
      try {
        const r = await fetch("/api/overlays/custom_points/presets");
        if (!r.ok) return;
        const presets = await r.json();
        const sel = document.getElementById("ov-custom-presets");
        if (!sel) return;
        // Clear existing options after default
        while (sel.options.length > 1) sel.remove(1);
        for (const p of presets) {
          const opt = document.createElement("option");
          opt.value = p.file;
          opt.textContent = `${p.name} (${p.count})`;
          sel.appendChild(opt);
        }
      } catch (e) { console.error("[CustomPoints] presets:", e); }
    },

    /** Load a preset file by name */
    async loadPreset(filename) {
      if (!filename) return;
      try {
        const r = await fetch(`/api/overlays/custom_points/preset/${filename}`);
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          const status = document.getElementById("ov-custom-status");
          if (status) status.textContent = err.error || "Failed to load";
          return;
        }
        _data = await r.json();
        _render();
        // Zoom to fit the points
        if (_data.length > 0) {
          const bounds = L.latLngBounds(_data.map(p => [p.lat, p.lon]));
          App.getMap().fitBounds(bounds, { padding: [50, 50] });
        }
      } catch (e) {
        console.error("[CustomPoints] loadPreset:", e);
      }
    },
  };
})();

// Wire into Overlays namespace
Overlays.toggleCustomPoints = function() { CustomPoints.toggle(); };
Overlays.customPoints = CustomPoints;

