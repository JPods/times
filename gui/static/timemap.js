/**
 * timemap.js — Walk-Ride-Walk coverage circles
 *
 * User clicks a point on the map.  For each time budget (5, 10, 20, 30 min)
 * the system draws:
 *   1. A circle at the clicked point — pure walking range
 *   2. A circle at each reachable station — remaining walk budget after
 *      walk-to-boarding + ride from boarding station to this station
 *
 * All circles of the same color are unioned into a single polygon using
 * Turf.js so only the outer boundary is visible — no interior circle lines.
 *
 * Requires a simulation to have been run (for ride times).
 * Walk-only circles always show even without simulation data.
 *
 * Algorithm matches Java TimeGraph.java:
 *   remaining = budget − walk_to_boarding_station − ride_time(boarding→dest)
 *   radius    = remaining × walk_speed_m_per_min
 *
 * Colors (matching Java TimeColor):
 *   Green  =  5 min total journey
 *   Blue   = 10 min
 *   Yellow = 20 min
 *   Red    = 30 min
 */

"use strict";

const TimeMap = (() => {

  let _active          = false;
  let _layers          = [];    // Leaflet GeoJSON layers currently on the map
  let _originMarker    = null;
  let _boardingMarker  = null;  // nearest-station pin (always shown)
  let _legend          = null;

  // Minimum walk-from-destination radius.  Below this the blob is too small to
  // be useful and reads as a map artefact rather than real coverage.
  const MIN_RADIUS_M = 300;

  // Max plausible pod speed (m/min).  Any ride_time that implies faster travel
  // is treated as a simulation artefact (disconnected-island phantom) and ignored.
  // 200 km/h = 3333 m/min — well above the 60 km/h (1000 m/min) cruise default.
  const MAX_SPEED_M_PER_MIN = 3333;

  // Draw largest budgets first so smaller (more reachable) areas render on top
  const BUDGETS = [30, 20, 10, 5];

  const STYLE = {
    5:  { color: "#00aa00", fillColor: "#00ff44" },
    10: { color: "#0044cc", fillColor: "#4488ff" },
    20: { color: "#aaaa00", fillColor: "#ffff00" },
    30: { color: "#cc2200", fillColor: "#ff6644" },
  };

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function _walkSpeedMperMin() {
    const kmh = parseFloat(
      document.getElementById("cfg-walkingSpeedKmh")?.value || 4.8
    );
    return kmh * 1000 / 60;
  }

  function _fillOpacity() {
    return parseFloat(
      document.getElementById("cfg-timemapOpacity")?.value || 0.15
    );
  }

  function _distMeters(lat1, lng1, lat2, lng2) {
    return L.latLng(lat1, lng1).distanceTo(L.latLng(lat2, lng2));
  }

  /**
   * Build a Turf polygon approximating a circle at (lat, lng) with radius metres.
   * steps=64 gives a smooth circle at planning-scale zoom levels.
   * Returns null if the radius is below MIN_RADIUS_M — suppresses micro-blobs.
   */
  function _turfCircle(lat, lng, radiusM) {
    if (radiusM < MIN_RADIUS_M) return null;
    return turf.circle([lng, lat], radiusM / 1000, { steps: 64, units: "kilometers" });
  }

  /**
   * Union an array of Turf polygon Features into one Feature.
   * Returns null if the array is empty.
   */
  function _unionAll(polygons) {
    const valid = polygons.filter(Boolean);
    if (valid.length === 0) return null;
    if (valid.length === 1) return valid[0];
    return valid.reduce((acc, p) => {
      try { return turf.union(acc, p); }
      catch (_) { return acc; }   // skip degenerate polygons
    });
  }

  // ── Legend ───────────────────────────────────────────────────────────────────

  function _showLegend() {
    if (_legend) return;
    _legend = L.control({ position: "bottomleft" });
    _legend.onAdd = () => {
      const div = L.DomUtil.create("div", "timemap-legend");
      div.innerHTML =
        `<div style="font-size:10px;color:#aaa;font-weight:600">&#9711; Coverage active</div>` +
        `<div style="margin-top:3px;font-size:10px;color:#888">` +
        `Click map point &nbsp;·&nbsp; Esc to exit</div>`;
      return div;
    };
    _legend.addTo(App.getMap());
  }

  function _hideLegend() {
    if (_legend) { _legend.remove(); _legend = null; }
  }

  // ── Clear ─────────────────────────────────────────────────────────────────────

  function _clearAll() {
    _layers.forEach(l => App.getLayers().timemap.removeLayer(l));
    _layers = [];
    if (_originMarker) {
      App.getLayers().timemap.removeLayer(_originMarker);
      _originMarker = null;
    }
    if (_boardingMarker) {
      App.getLayers().timemap.removeLayer(_boardingMarker);
      _boardingMarker = null;
    }
  }

  // ── Core algorithm ───────────────────────────────────────────────────────────

  function _draw(clickLat, clickLng) {
    _clearAll();

    const speedMperMin = _walkSpeedMperMin();
    const fillOpacity  = _fillOpacity();
    const MAX_BUDGET   = BUDGETS[0];   // 30 min (BUDGETS = [30, 20, 10, 5])

    // Station positions from last-fetched geojson
    const geojson  = Sim.getGeojson();
    const stations = {};
    if (geojson) {
      (geojson.features || [])
        .filter(f => f.properties.type === "station")
        .forEach(f => {
          const [lng, lat] = f.geometry.coordinates;
          stations[f.properties.node_id] = { lat, lng };
        });
    }
    const stationIds = Object.keys(stations);

    // Ride times from simulation trip_stats (minutes).
    // Filter out phantom entries: if the implied travel speed exceeds
    // MAX_SPEED_M_PER_MIN the time is a simulation artefact from a
    // disconnected-island station — skip it.
    const rideMins = {};
    const result = Sim.getResult();
    if (result) {
      (result.trip_stats || []).forEach(ts => {
        const ride_min = ts.median_trip_ms / 60000;
        // Guard against zero/near-zero times for non-adjacent stations
        if (ride_min > 0) {
          const orig = stations[ts.origin_id];
          const dest = stations[ts.dest_id];
          if (orig && dest) {
            const distM  = _distMeters(orig.lat, orig.lng, dest.lat, dest.lng);
            const impliedSpeed = distM / ride_min;  // m/min
            if (impliedSpeed > MAX_SPEED_M_PER_MIN) return;  // phantom — skip
          }
        }
        if (!rideMins[ts.origin_id]) rideMins[ts.origin_id] = {};
        rideMins[ts.origin_id][ts.dest_id] = ride_min;
      });
    }

    // Walk time (minutes) from clicked point to each station
    const walkToStation = {};
    stationIds.forEach(sid => {
      const s = stations[sid];
      walkToStation[sid] = _distMeters(clickLat, clickLng, s.lat, s.lng) / speedMperMin;
    });

    // Closest station = boarding station
    let boardingSid    = null;
    let walkToBoarding = Infinity;
    stationIds.forEach(sid => {
      if (walkToStation[sid] < walkToBoarding) {
        walkToBoarding = walkToStation[sid];
        boardingSid    = sid;
      }
    });

    // Origin marker (white dot at click point)
    _originMarker = L.circleMarker([clickLat, clickLng], {
      radius: 7, color: "#fff", weight: 2,
      fillColor: "#fff", fillOpacity: 1, interactive: false,
    });
    App.getLayers().timemap.addLayer(_originMarker);

    // Boarding station marker — always shown so the user can see the nearest
    // station even when it is beyond all time budgets.
    if (boardingSid) {
      const bs     = stations[boardingSid];
      const tooFar = walkToBoarding >= MAX_BUDGET;
      const bsName = boardingSid.replace(/\.PLATFORM$/, "");
      _boardingMarker = L.circleMarker([bs.lat, bs.lng], {
        radius:      8,
        color:       tooFar ? "#e74c3c" : "#f39c12",
        weight:      2.5,
        fillColor:   tooFar ? "#e74c3c" : "#f39c12",
        fillOpacity: 0.9,
        interactive: true,
      });
      _boardingMarker.bindTooltip(
        `${bsName}<br>${walkToBoarding.toFixed(1)} min walk` +
        (tooFar ? "<br>⚠ beyond 30 min budget" : ""),
        { direction: "top", className: "line-tooltip" }
      );
      App.getLayers().timemap.addLayer(_boardingMarker);
    }

    // Build + render one unioned polygon per budget
    BUDGETS.forEach(budget => {
      const st = STYLE[budget];
      const polys = [];

      // 1. Pure-walk circle at clicked point
      polys.push(_turfCircle(clickLat, clickLng, budget * speedMperMin));

      // 2. Destination station circles
      stationIds.forEach(destSid => {
        const s = stations[destSid];
        let remaining;

        if (destSid === boardingSid) {
          // Boarding station — no ride, just remaining walk budget
          if (walkToBoarding >= budget) return;
          remaining = budget - walkToBoarding;
        } else {
          if (!boardingSid) return;
          const ride = rideMins[boardingSid]?.[destSid];
          if (ride == null) return;
          const fixed = walkToBoarding + ride;
          if (fixed >= budget) return;
          remaining = budget - fixed;
        }

        polys.push(_turfCircle(s.lat, s.lng, remaining * speedMperMin));
      });

      const merged = _unionAll(polys);
      if (!merged) return;

      const layer = L.geoJSON(merged, {
        style: {
          color:       st.color,
          fillColor:   st.fillColor,
          fillOpacity,
          weight:      2,
          opacity:     0.9,
          interactive: false,
        },
        interactive: false,
      });
      App.getLayers().timemap.addLayer(layer);
      _layers.push(layer);
    });

    // Status message — always shows nearest station and warns when too far
    const hasRides = Object.keys(rideMins).length > 0;
    if (!boardingSid) {
      setStatus("Walk-Ride-Walk — no stations in network");
    } else {
      const bsName  = boardingSid.replace(/\.PLATFORM$/, "");
      const walkMin = walkToBoarding.toFixed(1);
      const tooFar  = walkToBoarding >= MAX_BUDGET;
      setStatus(
        tooFar
          ? `⚠ Nearest station ${bsName} is ${walkMin} min walk — beyond 30 min budget` +
            (hasRides ? "" : "  ·  Run simulation for ride-time circles")
          : `Walk-Ride-Walk — boarding: ${bsName} (${walkMin} min walk)` +
            (hasRides ? "" : "  ·  Run simulation for ride-time circles")
      );
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  return {

    toggle() {
      _active = !_active;
      const btn = document.getElementById("btn-timemap");
      if (btn) btn.classList.toggle("active", _active);
      App.getMap().getContainer().style.cursor = _active ? "crosshair" : "";
      if (_active) {
        _showLegend();
        setStatus("Walk-Ride-Walk: click any point on the map");
      } else {
        _hideLegend();
        _clearAll();
        setStatus("Ready");
      }
    },

    isActive() { return _active; },

    handleClick(lat, lng) {
      if (!_active) return false;
      _draw(lat, lng);
      return true;
    },

    clear() { _clearAll(); },

    deactivate() {
      _active = false;
      const btn = document.getElementById("btn-timemap");
      if (btn) btn.classList.remove("active");
      App.getMap().getContainer().style.cursor = "";
      _hideLegend();
      _clearAll();
    },

  };

})();

// ── Map click hook ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  App.getMap().on("click", (e) => {
    if (TimeMap.handleClick(e.latlng.lat, e.latlng.lng)) {
      L.DomEvent.stopPropagation(e);
    }
  });
});
