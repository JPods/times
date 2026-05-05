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
 * Ride times come from Dijkstra (analytical, always available) and are
 * upgraded to simulation medians where the sim has run — sim times include
 * station overhead and real congestion; analytical times are free-flow estimates.
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
  // Base budgets — 60-min ring is added dynamically when network spans >20 miles
  const BUDGETS_BASE = [30, 20, 10, 5];

  const STYLE = {
    5:  { color: "#00aa00", fillColor: "#00ff44" },
    10: { color: "#0044cc", fillColor: "#4488ff" },
    20: { color: "#aaaa00", fillColor: "#ffff00" },
    30: { color: "#cc2200", fillColor: "#ff6644" },
    60: { color: "#7700cc", fillColor: "#cc66ff" },
  };

  // Network span threshold (metres) above which a 60-min ring is drawn
  const LARGE_NETWORK_M = 32187;   // 20 miles

  // Compute the bounding-box diagonal of a set of {lat, lng} station objects
  function _networkSpanM(stations) {
    const lats = Object.values(stations).map(s => s.lat);
    const lngs = Object.values(stations).map(s => s.lng);
    if (lats.length < 2) return 0;
    return L.latLng(Math.min(...lats), Math.min(...lngs))
             .distanceTo(L.latLng(Math.max(...lats), Math.max(...lngs)));
  }

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
        `<div style="font-size:10px;color:#aaa;font-weight:600">&#9711; Isochrone active</div>` +
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

  async function _draw(clickLat, clickLng) {
    _clearAll();

    const speedMperMin = _walkSpeedMperMin();
    const fillOpacity  = _fillOpacity();

    // Station positions from last-fetched geojson
    const geojson  = Sim.getGeojson();
    const stations = {};
    if (geojson) {
      (geojson.features || [])
        .filter(f => f.properties.type === "station" &&
                     f.properties.structure_type !== "traffic_circle")
        .forEach(f => {
          const [lng, lat] = f.geometry.coordinates;
          stations[f.properties.node_id] = { lat, lng };
        });
    }
    const stationIds = Object.keys(stations);

    // Add 60-min ring when network spans more than 20 miles
    const span     = _networkSpanM(stations);
    const BUDGETS  = span > LARGE_NETWORK_M ? [60, ...BUDGETS_BASE] : BUDGETS_BASE;
    const MAX_BUDGET = BUDGETS[0];

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

    // ── Ride times: analytical (Dijkstra) with simulation overlay ────────────
    //
    // The simulation only produces trip_stats for O-D pairs that received ≥1
    // randomly generated passenger.  On a 60-station grid that leaves ~22% of
    // pairs blank by chance — enough to create visible isochrone holes.
    //
    // We fix this by fetching Dijkstra-based travel times from the API for the
    // boarding station.  Simulation medians (which include station overhead and
    // real congestion) are used where available; analytical times fill the rest.
    //
    // rideMins[boardingSid][destSid] = minutes

    const rideMins = {};

    // 1. Simulation data (preferred — includes overhead + congestion)
    const result = Sim.getResult();
    if (result) {
      (result.trip_stats || []).forEach(ts => {
        const ride_min = ts.median_trip_ms / 60000;
        if (ride_min > 0) {
          const orig = stations[ts.origin_id];
          const dest = stations[ts.dest_id];
          if (orig && dest) {
            const distM = _distMeters(orig.lat, orig.lng, dest.lat, dest.lng);
            if (distM / ride_min > MAX_SPEED_M_PER_MIN) return;  // phantom
          }
        }
        if (!rideMins[ts.origin_id]) rideMins[ts.origin_id] = {};
        rideMins[ts.origin_id][ts.dest_id] = ride_min;
      });
    }

    // 2. Analytical fill-in for the boarding station
    if (boardingSid) {
      try {
        const resp = await fetch(`/api/network/travel_times?origin=${encodeURIComponent(boardingSid)}`);
        if (resp.ok) {
          const data = await resp.json();
          if (!rideMins[boardingSid]) rideMins[boardingSid] = {};
          Object.entries(data.travel_min || {}).forEach(([destId, mins]) => {
            // Only fill gaps — simulation data takes precedence
            if (rideMins[boardingSid][destId] == null) {
              rideMins[boardingSid][destId] = mins;
            }
          });
        }
      } catch (_) { /* network error — isochrone continues with sim data only */ }
    }

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
        (tooFar ? `<br>⚠ beyond ${MAX_BUDGET} min budget` : ""),
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

    // Station reach markers — dot at each station showing ride time and total time.
    // Lets the user identify specific anomalies by station name (s1, s2, etc.).
    if (boardingSid) {
      // Pre-build set of dest IDs that have real simulation data from this boarding station
      const simDestSet = new Set();
      if (result) {
        (result.trip_stats || []).forEach(ts => {
          if (ts.origin_id === boardingSid) simDestSet.add(ts.dest_id);
        });
      }

      stationIds.forEach(destSid => {
        if (destSid === boardingSid) return;  // boarding marker already shown
        const s = stations[destSid];
        const ride = rideMins[boardingSid]?.[destSid];
        const name = destSid.replace(/\.PLATFORM$/, "");

        let dotColor, totalMin, rideMin;
        if (ride == null) {
          dotColor = "#888";
          rideMin  = null;
          totalMin = null;
        } else {
          rideMin  = ride;
          totalMin = walkToBoarding + rideMin;
          if      (totalMin < 5)  dotColor = STYLE[5].color;
          else if (totalMin < 10) dotColor = STYLE[10].color;
          else if (totalMin < 20) dotColor = STYLE[20].color;
          else if (totalMin < 30) dotColor = STYLE[30].color;
          else if (totalMin < 60) dotColor = STYLE[60].color;
          else                    dotColor = "#888";
        }

        // "~" marks analytical (Dijkstra) estimate; no prefix = simulation median
        const isSim = simDestSet.has(destSid);
        const tip = ride == null
          ? `<b>${name}</b><br>no route`
          : isSim
            ? `<b>${name}</b><br>${rideMin.toFixed(1)} min ride (sim)<br>${totalMin.toFixed(1)} min total`
            : `<b>${name}</b><br>~${rideMin.toFixed(1)} min ride (est)<br>~${totalMin.toFixed(1)} min total`;

        const dot = L.circleMarker([s.lat, s.lng], {
          radius:      4,
          color:       "#222",
          weight:      1,
          fillColor:   dotColor,
          fillOpacity: 0.9,
          interactive: true,
        });
        dot.bindTooltip(tip, { direction: "top", className: "line-tooltip" });
        App.getLayers().timemap.addLayer(dot);
        _layers.push(dot);
      });
    }

    // Status message — always shows nearest station and warns when too far
    const hasSim = result && (result.trip_stats || []).length > 0;
    if (!boardingSid) {
      setStatus("Isochrone — no stations in network");
    } else {
      const bsName  = boardingSid.replace(/\.PLATFORM$/, "");
      const walkMin = walkToBoarding.toFixed(1);
      const tooFar  = walkToBoarding >= MAX_BUDGET;
      const simNote = hasSim ? "" : "  ·  est. times (run sim for congestion data)";
      setStatus(
        tooFar
          ? `⚠ Nearest station ${bsName} is ${walkMin} min walk — beyond ${MAX_BUDGET} min budget`
          : `Isochrone — boarding: ${bsName} (${walkMin} min walk)${simNote}`
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
        setStatus("Isochrone: click any point on the map");
      } else {
        _hideLegend();
        _clearAll();
        setStatus("Ready");
      }
    },

    isActive() { return _active; },

    handleClick(lat, lng) {
      if (!_active) return false;
      setStatus("Isochrone — computing…");
      _draw(lat, lng);   // async — returns Promise; fire-and-forget is fine
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
