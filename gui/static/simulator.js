/**
 * simulator.js — Run simulation and animate pod positions.
 *
 * Simulation is physics-based (transit_time_ms per line).
 * After a run, we build a frame sequence client-side from the results
 * and replay it on the map.
 *
 * Pod color: white=parked, blue=dispatched, red→green=velocity ratio
 * (matching Java PodPainter).
 */

"use strict";

const Sim = (() => {

  let _result      = null;
  let _geojson     = null;  // last-fetched network GeoJSON (reused by TimeMap)
  let _frames      = [];    // [{pods: [{lat,lng,color}]}, ...]
  let _frameIdx    = 0;
  let _animTimer   = null;
  let _loadingAnim = null;  // interval handle for the sim-running loading animation
  let _podMarkers  = [];

  // HSV interpolation red→green for velocity ratio 0→1
  function _podColor(ratio) {
    // Hue: 0° = red, 120° = green
    const h = Math.round(ratio * 120);
    return `hsl(${h},100%,50%)`;
  }

  function _clearPods() {
    _podMarkers.forEach(m => App.getLayers().pods.removeLayer(m));
    _podMarkers = [];
  }

  function _drawPods(podList) {
    _clearPods();
    podList.forEach(({ lat, lng, color, label, isStopping, isApproaching }) => {
      // Size: 16 = at station siding, 12 = approaching destination, 8 = cruising
      const sz     = isStopping ? 16 : isApproaching ? 12 : 8;
      const border = isStopping ? '2px solid #fff' : isApproaching ? '1px solid rgba(255,255,255,0.6)' : 'none';
      const icon = L.divIcon({
        className: "",
        html: `<div class="pod-marker" style="background:${color};width:${sz}px;height:${sz}px;border-radius:50%;border:${border}" title="${label||''}"></div>`,
        iconSize:   [sz, sz],
        iconAnchor: [sz / 2, sz / 2],
      });
      const m = L.marker([lat, lng], { icon, interactive: false });
      App.getLayers().pods.addLayer(m);
      _podMarkers.push(m);
    });
  }

  // Build animation frames — one pod per station-to-station route.
  // Each pod travels the full path: origin platform → guideways → destination platform.
  //
  // Cycle structure (per route):
  //   [DWELL at origin] [TRAVEL] [DWELL at destination] [empty return - instant]
  //
  // DWELL_FRAC: fraction of cycle the pod sits parked at each end.
  // Parked pods show white; travelling pods show red→green→red (velocity bell).
  async function _buildFrames(result, geojson) {
    _frames = [];

    const DWELL_FRAC = 0.15;   // 15% of each cycle parked at origin, 15% at dest

    // Index line geometries by line_id
    const lineFeatures = {};
    geojson.features
      .filter(f => f.properties.type === "line")
      .forEach(f => { lineFeatures[f.properties.line_id] = f; });

    // Siding line suffixes — pod is "stopping" only while on these segments
    const SIDING_SUFFIXES = [
      "platform_in", "platform_parking_a", "platform_parking_b",
      "platform_out",
    ];

    // Physics settings from panel (for transit time weighting)
    const maxKmph = parseFloat(document.getElementById("cfg-maxVelocityInKMPH")?.value || 60);
    const accG    = parseFloat(document.getElementById("cfg-accInG")?.value || 1.0);
    const vMax    = maxKmph / 3.6;       // m/s
    const acc     = accG * 9.81;         // m/s²
    const lFull   = vMax * vMax / acc;   // distance to reach full speed

    // Physics transit time for a single line segment
    function _segTransitMs(length_m) {
      const L = Math.max(length_m, 0.1);
      const t = L >= lFull
        ? 2 * vMax / acc + (L - lFull) / vMax   // accel + cruise + decel
        : 2 * Math.sqrt(L / acc);                // short: accel+decel only
      return t * 1000;
    }

    // Build full-route coordinate chains from trip_stats
    const routes = [];
    (result.trip_stats || []).forEach(ts => {
      if (!ts.route_line_ids || ts.route_line_ids.length === 0) return;
      if (!ts.median_trip_ms) return;

      // Build per-line segment data.
      // Each segment carries:
      //   - coords: geographic points for position interpolation
      //   - segDeg: cumulative coordinate-degree length (for _interpolateChain)
      //   - transitMs: physics time on this segment (for time-based travelRatio)
      //   - isSiding: whether it is a station access line
      const lineSegs = [];
      let totalDeg = 0;
      let totalTransitMs = 0;

      ts.route_line_ids.forEach(lid => {
        const feat = lineFeatures[lid];
        if (!feat) return;
        const c = feat.geometry.coordinates; // [[lng,lat], ...]
        const length_m = feat.properties.length_m || 1;

        // Geographic length in degrees (for coord-chain interpolation)
        let segDeg = 0;
        for (let i = 0; i < c.length - 1; i++) {
          const dx = c[i+1][0] - c[i][0];
          const dy = c[i+1][1] - c[i][1];
          segDeg += Math.sqrt(dx*dx + dy*dy);
        }

        const transitMs = _segTransitMs(length_m);
        lineSegs.push({
          coords: c, lineId: lid,
          segDeg, transitMs,
          isSiding: SIDING_SUFFIXES.some(s => lid.endsWith(s)),
          isApproaching: false,   // filled in below
        });
        totalDeg       += segDeg;
        totalTransitMs += transitMs;
      });

      // Tag near-guideway lines of the destination station as "approaching".
      // A segment is approaching when it belongs to the dest station's structure
      // (lid starts with dest_id + '.') AND it is NOT a siding line AND the
      // route does contain siding lines (confirming this pod is stopping there,
      // not just passing through that station's body).
      const destPrefix   = ts.dest_id + '.';
      const routeHasSiding = lineSegs.some(s => s.isSiding);
      if (routeHasSiding) {
        lineSegs.forEach(seg => {
          if (!seg.isSiding && seg.lineId.startsWith(destPrefix)) {
            seg.isApproaching = true;
          }
        });
      }

      if (lineSegs.length === 0 || totalDeg === 0 || totalTransitMs === 0) return;

      // Assign time-based fractions (used for isStopping and speed display)
      // and geographic fractions (used for position in _interpolateChain).
      let cumMs  = 0;
      let cumDeg = 0;
      const coords = [];
      lineSegs.forEach(seg => {
        seg.startTimeFrac = cumMs  / totalTransitMs;
        seg.endTimeFrac   = (cumMs  + seg.transitMs) / totalTransitMs;
        seg.startGeoFrac  = cumDeg / totalDeg;
        seg.endGeoFrac    = (cumDeg + seg.segDeg)    / totalDeg;
        cumMs  += seg.transitMs;
        cumDeg += seg.segDeg;

        if (coords.length === 0) {
          coords.push(...seg.coords);
        } else {
          coords.push(...seg.coords.slice(1));
        }
      });

      if (coords.length < 2) return;

      routes.push({
        coords,
        lineSegs,
        totalDeg,
        transit_ms: ts.median_trip_ms,
        label: `${ts.origin_id} → ${ts.dest_id}`,
        origin: coords[0],
        dest:   coords[coords.length - 1],
      });
    });

    if (routes.length === 0) return;

    const fps = 12;
    const totalFrames = fps * 10;  // 10-second loop

    // Normalise so slowest route sets the cycle length
    const maxMs = Math.max(...routes.map(r => r.transit_ms));

    for (let frame = 0; frame < totalFrames; frame++) {
      const t = frame / totalFrames;  // 0..1 across replay window
      const pods = [];

      routes.forEach(route => {
        // Each route has a cycle proportional to its transit time
        const cycleT = route.transit_ms / maxMs;   // 0..1 relative to slowest
        const rawPos = (t / Math.max(cycleT, 0.001)) % 1;  // position in THIS route's cycle

        let travelRatio;  // 0 = origin platform, 1 = dest platform
        let baseColor;

        if (rawPos < DWELL_FRAC) {
          // ── Parked at origin station ──
          travelRatio = 0;
          baseColor = "#ffffff";   // white = parked / loading
        } else if (rawPos > 1 - DWELL_FRAC) {
          // ── Parked at destination station ──
          travelRatio = 1;
          baseColor = "#ffffff";   // white = parked / unloading
        } else {
          // ── Travelling ──
          travelRatio = (rawPos - DWELL_FRAC) / (1 - 2 * DWELL_FRAC);
          // Bell-shaped velocity: green at cruise, red at platforms
          const phase = Math.min(travelRatio * 4, 1) * Math.min((1 - travelRatio) * 4, 1);
          baseColor = _podColor(phase);
        }

        // Determine current segment by time fraction (physics-accurate)
        const curSeg = route.lineSegs.find(s =>
          travelRatio >= s.startTimeFrac && travelRatio <= s.endTimeFrac
        ) || route.lineSegs[route.lineSegs.length - 1];
        const isStopping    = curSeg.isSiding;
        const isApproaching = curSeg.isApproaching;

        // Color by state (overrides velocity color for non-parked pods):
        //   orange  = on station siding (exit / platform / reentry)
        //   yellow  = on destination station's near-guideway (about to peel off)
        //   red→grn = cruising on through guideway
        //   white   = parked / loading
        let color = baseColor;
        if (baseColor !== "#ffffff") {
          if (isStopping)      color = "#e67e22";   // orange  — in station
          else if (isApproaching) color = "#f1c40f"; // yellow  — approaching
        }

        // Convert time fraction → geographic fraction for position
        const segTimeFrac = (curSeg.endTimeFrac > curSeg.startTimeFrac)
          ? (travelRatio - curSeg.startTimeFrac) / (curSeg.endTimeFrac - curSeg.startTimeFrac)
          : 0;
        const geoFrac = curSeg.startGeoFrac + segTimeFrac * (curSeg.endGeoFrac - curSeg.startGeoFrac);

        const pos = _interpolateChain(route.coords, geoFrac);
        pods.push({
          lat: pos[1], lng: pos[0],
          color,
          label: route.label,
          isStopping,
          isApproaching,
        });
      });

      _frames.push({ pods });
    }
  }

  function _interpolateChain(coords, t) {
    // Total chain length
    let totalLen = 0;
    const segs = [];
    for (let i = 0; i < coords.length - 1; i++) {
      const dx = coords[i+1][0] - coords[i][0];
      const dy = coords[i+1][1] - coords[i][1];
      const len = Math.sqrt(dx*dx + dy*dy);
      segs.push({ start: coords[i], end: coords[i+1], len });
      totalLen += len;
    }
    let target = t * totalLen;
    for (const seg of segs) {
      if (target <= seg.len) {
        const frac = seg.len > 0 ? target / seg.len : 0;
        return [
          seg.start[0] + frac * (seg.end[0] - seg.start[0]),
          seg.start[1] + frac * (seg.end[1] - seg.start[1]),
        ];
      }
      target -= seg.len;
    }
    return coords[coords.length - 1];
  }

  function _replayIntervalMs() {
    // Read speed multiplier from settings panel (default 360×)
    const mult = parseFloat(
      document.getElementById("cfg-simSpeedMultiplier")?.value || 360
    );
    // Base: 12 fps at 360×.  Scale interval inversely with multiplier.
    const baseInterval = 1000 / 12;
    return Math.max(16, Math.round(baseInterval * 360 / mult));
  }

  function _startReplay() {
    if (_animTimer) clearInterval(_animTimer);
    _frameIdx = 0;
    const interval = _replayIntervalMs();
    _animTimer = setInterval(() => {
      if (_frameIdx >= _frames.length) {
        _frameIdx = 0; // loop
      }
      _drawPods(_frames[_frameIdx].pods);
      _frameIdx++;
    }, interval);
  }

  function _stopReplay() {
    if (_animTimer) { clearInterval(_animTimer); _animTimer = null; }
    _clearPods();
  }

  // ── Loading animation (runs while simulation POST is in flight) ─────────────
  // Accepts pre-fetched geojson to avoid a race between the animation start
  // and the simulation response completing before the inner GET returns.

  function _startLoadingAnim(geojson) {
    if (_loadingAnim) return;

    const lines = (geojson.features || []).filter(f => f.properties.type === "line");
    if (lines.length === 0) return;

    // Group lines by their end_node — pods heading to the same junction
    // will naturally bunch there, showing likely congestion points.
    // No phase offset: all pods on connected paths advance in lock-step,
    // so they pile up at merge points just as real vehicles would.
    const nodeGroups = {};
    lines.forEach(feat => {
      const endNode = feat.properties.end_node || feat.properties.line_id;
      if (!nodeGroups[endNode]) nodeGroups[endNode] = [];
      nodeGroups[endNode].push(feat);
    });

    // Assign each pod a start offset proportional to its line length,
    // so pods enter their line at the right spacing for the given headway.
    const headwaySec = parseFloat(
      document.getElementById("cfg-minHeadwaySec")?.value || 0.25
    );
    const speedKmh = parseFloat(
      document.getElementById("cfg-maxVelocityInKMPH")?.value || 60
    );
    const speedMs = speedKmh / 3.6;

    // Pods per line = floor(line_length / (speed × headway + pod_len))
    // Each pod has its own phase offset within that line's capacity
    const podLen = parseFloat(document.getElementById("cfg-podLen")?.value || 3);
    const minSpacingM = speedMs * headwaySec + podLen;

    let tick = 0;
    const fps = 10;
    const LOOP_S = 6;  // seconds for one pass along a line
    const ticksPerLoop = fps * LOOP_S;

    _loadingAnim = setInterval(() => {
      const podList = [];

      lines.forEach(feat => {
        const coords = feat.geometry.coordinates;
        if (coords.length < 2) return;

        // Estimate line length in degrees (proportional approximation)
        let degLen = 0;
        for (let i = 0; i < coords.length - 1; i++) {
          const dx = coords[i+1][0] - coords[i][0];
          const dy = coords[i+1][1] - coords[i][1];
          degLen += Math.sqrt(dx*dx + dy*dy);
        }
        const lineLen_m = feat.properties.length_m || (degLen * 111000);
        const maxPods   = Math.max(1, Math.floor(lineLen_m / minSpacingM));
        const count     = Math.min(maxPods, 8);  // cap display pods per line

        for (let p = 0; p < count; p++) {
          // No stagger — pods are evenly spaced by headway, NOT randomly offset
          // so they bunch at shared nodes the same way real traffic does
          const spacingFrac = (minSpacingM / lineLen_m) || (1 / count);
          const ratio = ((tick / ticksPerLoop) + p * spacingFrac) % 1;

          const pos = _interpolateChain(coords, ratio);
          podList.push({
            lat: pos[1], lng: pos[0],
            color: "#3498db",   // solid blue — loading indicator
            label: feat.properties.line_id || "",
          });
        }
      });

      _clearPods();
      podList.forEach(({ lat, lng, color, label }) => {
        const icon = L.divIcon({
          className: "",
          html: `<div class="pod-marker" style="background:${color}" title="${label}"></div>`,
          iconSize: [8, 8], iconAnchor: [4, 4],
        });
        const m = L.marker([lat, lng], { icon, interactive: false });
        App.getLayers().pods.addLayer(m);
        _podMarkers.push(m);
      });

      tick++;
    }, 1000 / fps);
  }

  function _stopLoadingAnim() {
    if (_loadingAnim) { clearInterval(_loadingAnim); _loadingAnim = null; }
    _clearPods();
  }

  // ── Sweep progress circles ─────────────────────────────────────────────────
  // Orange rings around each station while it still has pending sweep trips.
  let _sweepCircles = {};   // station node_id → L.circleMarker

  function _showSweepCircles(geojson) {
    _sweepCircles = {};
    (geojson.features || [])
      .filter(f => f.properties.type === "station")
      .forEach(f => {
        const [lng, lat] = f.geometry.coordinates;
        const sid = f.properties.node_id;
        const m = L.circleMarker([lat, lng], {
          radius: 14, color: "#FF8C00", weight: 3, fill: false, interactive: false,
        });
        App.getLayers().pods.addLayer(m);
        _sweepCircles[sid] = m;
      });
  }

  function _clearSweepCirclesFor(completedSids) {
    (completedSids || []).forEach(sid => {
      const m = _sweepCircles[sid];
      if (m) { App.getLayers().pods.removeLayer(m); delete _sweepCircles[sid]; }
    });
  }

  function _clearSweepCircles() {
    Object.values(_sweepCircles).forEach(m => App.getLayers().pods.removeLayer(m));
    _sweepCircles = {};
  }

  function _fmtMin(min) {
    if (!min && min !== 0) return "—";
    const m = Math.floor(min), s = Math.round((min - m) * 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  function _panelRow(label, value) {
    return `<div class="sim-line-row"><span style="color:#aaa">${label}</span><span>${value}</span></div>`;
  }

  function _sectionHead(title) {
    return `<div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.5px;margin:8px 0 3px;border-top:1px solid #333;padding-top:5px">${title}</div>`;
  }

  // Grid color helpers — used by _showResults and _fillGridGaps
  function _timeColor(ms, est) {
    if (ms == null) return "#1a1a1a";
    const min = ms / 60000;
    const alpha = est ? "0.6" : "1";
    if (min <  5) return `rgba(102,255,0,${alpha})`;
    if (min < 10) return `rgba(191,255,0,${alpha})`;
    if (min < 15) return `rgba(255,255,49,${alpha})`;
    if (min < 20) return `rgba(255,219,88,${alpha})`;
    if (min < 25) return `rgba(255,179,71,${alpha})`;
    if (min < 30) return `rgba(255,90,54,${alpha})`;
    return `rgba(255,28,0,${alpha})`;
  }
  function _textColor(ms) {
    if (ms == null) return "#555";
    return (ms / 60000) < 15 ? "#111" : "#fff";
  }
  function _fmtCell(ms, est) {
    if (ms == null) return "—";
    const sec = Math.round(ms / 1000);
    const m = Math.floor(sec / 60), s = sec % 60;
    const t = m > 0 ? `${m}m${s}s` : `${sec}s`;
    return est ? `~${t}` : t;
  }
  function _cellId(orig, dest) {
    return `gc-${orig.replace(/[^a-zA-Z0-9]/g, "_")}-${dest.replace(/[^a-zA-Z0-9]/g, "_")}`;
  }

  function _showResults(result) {
    _result = result;
    document.getElementById("panel-sim").style.display = "";

    const sim = result.simulation || {};
    const sm  = result.summary   || {};
    const pct = sim.passengers_generated
      ? ((sim.passengers_served / sim.passengers_generated) * 100).toFixed(1) : "—";

    // Header summary
    document.getElementById("sim-summary").innerHTML =
      `<b>${sim.passengers_served}</b> / ${sim.passengers_generated} passengers (${pct}%)`;

    let html = "";

    // --- CAPACITY ---
    html += _sectionHead("Capacity");
    html += _panelRow("Carried",    sm.passengers_carried   ?? "—");
    html += _panelRow("Travelling", sm.passengers_travelling ?? "—");
    html += _panelRow("Waiting",    sm.passengers_waiting   ?? "—");
    html += _panelRow("Throughput", sm.throughput_per_hour != null ? `${sm.throughput_per_hour}/hr` : "—");

    // --- VELOCITY ---
    html += _sectionHead("Velocity (km/h)");
    html += _panelRow("Avg",     sm.avg_velocity_kmph     ?? "—");
    html += _panelRow("Slowest", sm.slowest_velocity_kmph ?? "—");

    // --- TIMINGS ---
    const walkToSec   = parseFloat(document.getElementById("cfg-walkToStationSec")?.value   || 300);
    const walkFromSec = parseFloat(document.getElementById("cfg-walkFromStationSec")?.value || 300);
    const walkTotalMin = (walkToSec + walkFromSec) / 60;
    const avgDoorMin   = sm.avg_trip_time_min != null
      ? Math.round((sm.avg_trip_time_min + walkTotalMin) * 10) / 10 : null;

    html += _sectionHead("Timings");
    html += _panelRow("Avg guideway",   _fmtMin(sm.avg_trip_time_min));
    html += _panelRow("Walk overhead",  `+${_fmtMin(walkTotalMin)}`);
    html += _panelRow("Avg door-to-door", _fmtMin(avgDoorMin));
    html += _panelRow("Longest trip",   _fmtMin(sm.longest_trip_time_min));
    html += _panelRow("Longest wait",   _fmtMin(sm.longest_wait_time_min));

    // --- DISTANCE ---
    html += _sectionHead("Distance (km)");
    html += _panelRow("Avg trip",  sm.avg_trip_distance_km   != null ? sm.avg_trip_distance_km   : "—");
    html += _panelRow("Total",     sm.total_trip_distance_km != null ? sm.total_trip_distance_km : "—");

    // --- RUN ---
    html += _sectionHead("Run");
    html += _panelRow("Simulated", sm.simulated_time_hms ?? "—");
    html += _panelRow("Machine",   sm.machine_time_hms   ?? "—");

    // --- NETWORK ---
    html += _sectionHead("Network");
    html += _panelRow("Stations",    sm.station_count    ?? "—");
    html += _panelRow("Lines",       sm.line_count       ?? "—");
    html += _panelRow("Length (km)", sm.total_network_km ?? "—");
    html += _panelRow("Total pods",  sm.total_pods       ?? "—");

    // --- STATIONS (convergences/divergences — what Java called Switches) ---
    html += _sectionHead("Stations");
    html += _panelRow("Convergences", sm.convergence_count ?? "—");
    html += _panelRow("Divergences",  sm.divergence_count  ?? "—");

    // --- ROUTE GRID (origin × destination matrix, color by travel time) ---
    // All stations from station_stats — guarantees every station appears even
    // if it had zero completed trips.  Gaps filled analytically after render.
    const allStationIds = (result.station_stats || [])
      .map(st => st.station_id).sort();

    // Build lookup: "origin|dest" → median_trip_ms (from completed trips)
    const gridLookup = {};
    (result.trip_stats || []).forEach(t => {
      gridLookup[`${t.origin_id}|${t.dest_id}`] = t.median_trip_ms;
    });

    if (allStationIds.length > 0) {
      // Strip .PLATFORM suffix and any legacy hex prefix, keep the s# / c# label
      const short = id => id.replace(/\.PLATFORM$/, "").replace(/^[A-Z]+_[0-9A-F]+$/, id);
      html += _sectionHead("Route Grid");
      html += `<div style="font-size:10px;color:#666;margin-bottom:3px">` +
              `Rows=origin · Cols=destination · Color=trip time · ~=analytical estimate</div>`;

      let tbl = `<table style="border-collapse:collapse;font-size:9px;width:100%">`;
      tbl += `<tr><th style="background:#111;padding:2px"></th>`;
      allStationIds.forEach(dest => {
        tbl += `<th style="background:#111;color:#888;padding:2px;text-align:center;` +
               `writing-mode:vertical-rl;transform:rotate(180deg);max-width:28px" ` +
               `title="${dest}">${short(dest)}</th>`;
      });
      tbl += `</tr>`;
      allStationIds.forEach(origin => {
        tbl += `<tr><td style="background:#111;color:#888;padding:2px 3px;white-space:nowrap" ` +
               `title="${origin}">${short(origin)}</td>`;
        allStationIds.forEach(dest => {
          if (origin === dest) {
            tbl += `<td style="background:#111;text-align:center;padding:1px">·</td>`;
          } else {
            const ms  = gridLookup[`${origin}|${dest}`];
            const bg  = _timeColor(ms, false);
            const fg  = _textColor(ms);
            const cid = _cellId(origin, dest);
            tbl += `<td id="${cid}" style="background:${bg};color:${fg};text-align:center;` +
                   `padding:1px;min-width:24px" title="${origin}→${dest}: ${_fmtCell(ms, false)}">` +
                   `${_fmtCell(ms, false)}</td>`;
          }
        });
        tbl += `</tr>`;
      });
      tbl += `</table>`;
      html += tbl;

      html += `<div style="display:flex;gap:3px;margin-top:4px;font-size:9px;align-items:center">
        <span style="background:rgb(102,255,0);width:14px;height:10px;display:inline-block;border-radius:2px"></span>&lt;5m
        <span style="background:rgb(255,255,49);width:14px;height:10px;display:inline-block;border-radius:2px"></span>&lt;15m
        <span style="background:rgb(255,90,54);width:14px;height:10px;display:inline-block;border-radius:2px"></span>&lt;30m
        <span style="background:rgb(255,28,0);width:14px;height:10px;display:inline-block;border-radius:2px"></span>30m+
        <span style="opacity:0.6;background:rgb(191,255,0);width:14px;height:10px;display:inline-block;border-radius:2px"></span>~est
      </div>`;
    }

    // --- TRIP TIMES (origin → destination) ---
    const trips = [...(result.trip_stats || [])]
      .sort((a, b) => (b.median_trip_ms || 0) - (a.median_trip_ms || 0));
    if (trips.length > 0) {
      const oh = Math.round((trips[0].station_overhead_ms || 0) / 1000);
      html += _sectionHead(`Trip Times (incl. ${oh}s station overhead)`);
      html += `<div class="sim-line-row" style="font-size:10px;color:#666">Origin → Dest<span>Median</span><span>n</span></div>`;
      trips.forEach(ts => {
        const sec = Math.round(ts.median_trip_ms / 1000);
        const m = Math.floor(sec / 60), s = sec % 60;
        const lbl = m > 0 ? `${m}m ${s}s` : `${sec}s`;
        html += `<div class="sim-line-row">
          <span style="font-size:10px;line-height:1.3">${ts.origin_id}<br>→ ${ts.dest_id}</span>
          <span>${lbl}</span><span style="color:#666">${ts.sample_count}</span></div>`;
      });
    } else {
      html += _sectionHead("Trip Times");
      html += `<div style="color:#666;font-size:11px">No trips completed — check network connectivity</div>`;
    }

    // --- LINE DATA (congestion) ---
    const lines = [...(result.line_stats || [])]
      .filter(l => l.pods_arrived > 0)
      .sort((a, b) => (b.congestion || 0) - (a.congestion || 0));
    if (lines.length > 0) {
      html += _sectionHead("Line Data");
      html += `<div class="sim-line-row" style="font-size:10px;color:#666">Line<span>In/Out</span><span>Avg s</span><span>Cong</span></div>`;
      lines.forEach(l => {
        const cong = l.congestion != null ? l.congestion : 0;
        const hue  = Math.round((1 - Math.min(cong, 1)) * 120);
        const bar  = `<span style="display:inline-block;width:28px;height:8px;border-radius:2px;background:hsl(${hue},80%,45%);vertical-align:middle"></span>`;
        html += `<div class="sim-line-row" style="font-size:10px">
          <span title="${l.line_id}">${l.line_id.slice(-8)}</span>
          <span>${l.pods_arrived}</span>
          <span>${l.avg_time_s ?? "—"}</span>
          <span>${bar}</span></div>`;
      });
    }

    // --- STATION DATA ---
    const stationData = [...(result.station_stats || [])]
      .sort((a, b) => (b.passengers_boarded + b.passengers_alighted) -
                      (a.passengers_boarded + a.passengers_alighted));
    if (stationData.length > 0) {
      html += _sectionHead("Station Data");
      html += `<div class="sim-line-row" style="font-size:10px;color:#666">Station<span>Boarded</span><span>Alighted</span></div>`;
      stationData.forEach(st => {
        html += `<div class="sim-line-row" style="font-size:10px">
          <span title="${st.station_id}">${st.station_id.slice(-10)}</span>
          <span>${st.passengers_boarded}</span>
          <span>${st.passengers_alighted}</span></div>`;
      });
    }

    document.getElementById("sim-lines").innerHTML = html;

    // Async: fill any dark/missing Route Grid cells with analytical estimates
    if (allStationIds.length > 0) {
      _fillGridGaps(allStationIds, gridLookup).catch(e => console.warn("Grid gap fill:", e));
    }
  }

  async function _fillGridGaps(allStationIds, lookup) {
    // Find which origins have at least one missing destination
    const originsWithGaps = allStationIds.filter(orig =>
      allStationIds.some(dest => dest !== orig && lookup[`${orig}|${dest}`] == null)
    );

    for (const orig of originsWithGaps) {
      let data;
      try {
        const resp = await fetch(`/api/network/travel_times?origin=${encodeURIComponent(orig)}`);
        if (!resp.ok) continue;
        data = await resp.json();
      } catch (_) { continue; }

      const travelMin = data.travel_min || {};
      allStationIds.forEach(dest => {
        if (dest === orig) return;
        if (lookup[`${orig}|${dest}`] != null) return;  // already has sim data
        const min = travelMin[dest];
        if (min == null) return;
        const ms   = min * 60_000;
        const cell = document.getElementById(_cellId(orig, dest));
        if (!cell) return;
        cell.style.background = _timeColor(ms, true);
        cell.style.color      = _textColor(ms);
        cell.title            = `${orig}→${dest}: ${_fmtCell(ms, true)} (analytical)`;
        cell.textContent      = _fmtCell(ms, true);
      });
    }
  }

  return {

    async run() {
      const slots = parseInt(document.getElementById("sim-slots").value, 10) || 360;
      setStatus("Running simulation… ⏳");
      _stopReplay();

      // Pre-fetch network geometry so loading animation starts immediately
      _geojson = await api("GET", "/api/network");
      _startLoadingAnim(_geojson);
      _showSweepCircles(_geojson);   // orange rings on all stations

      // Start async simulation — send current panel settings so server uses live values
      const started = await api("POST", "/api/simulation/run", { slots, settings: Settings.current() });
      if (started.error) {
        _stopLoadingAnim();
        _clearSweepCircles();
        alert(started.error);
        return;
      }

      // Poll progress every 800 ms
      let result = null;
      let dotCount = 0;
      while (!result) {
        await new Promise(r => setTimeout(r, 800));
        const prog = await api("GET", "/api/simulation/progress");

        if (prog.status === "done") {
          result = prog.result;
        } else if (prog.status === "error") {
          _stopLoadingAnim();
          _clearSweepCircles();
          alert("Simulation error: " + (prog.error || "unknown"));
          return;
        } else if (prog.status === "running") {
          // Remove orange ring from each station that has completed all sweeps
          _clearSweepCirclesFor(prog.completed_origins || []);
          const n    = prog.total_stations || 0;
          const done = (prog.completed_origins || []).length;
          const cp   = prog.covered_pairs  || 0;
          const tp   = prog.total_pairs    || (n * (n - 1));
          const dots = ".".repeat((dotCount++ % 3) + 1);
          setStatus(`Running simulation${dots} ${done}/${n} stations · ${cp}/${tp} pairs`);
        }
      }

      _stopLoadingAnim();
      _clearSweepCircles();

      if (result.error) { alert(result.error); return; }

      _result = result;
      _showResults(result);
      await _buildFrames(result, _geojson);

      document.getElementById("btn-replay").disabled = false;
      document.getElementById("btn-replay").textContent = "▶▶ Replay";
      const pax = result.simulation.passengers_served;
      setStatus(`Simulation complete — ${pax} passengers served`);
      App.setReadOnly(true);
    },

    replay() {
      if (!_frames.length) { alert("Run simulation first."); return; }
      if (_animTimer) {
        _stopReplay();
        document.getElementById("btn-replay").textContent = "▶▶ Replay";
        setStatus("Replay stopped");
      } else {
        _startReplay();
        document.getElementById("btn-replay").textContent = "⏹ Stop";
        setStatus("Replaying simulation…");
      }
    },

    closeResults() {
      _stopReplay();
      document.getElementById("panel-sim").style.display = "none";
      document.getElementById("btn-replay").textContent = "▶▶ Replay";
      document.getElementById("btn-replay").disabled = true;
      setStatus("Ready");
    },

    // ── Focus mode: rebuild frames for a single station ─────────────────
    // Shows only routes whose line list includes an internal line of sid.
    // Runs at slow speed (60× default) so behavior is easy to follow.
    // Call clearFocus() or Replay to return to full-network view.
    async focusStation(sid) {
      if (!_result) { alert("Run simulation first."); return; }
      if (!_geojson) return;

      // Filter to trips whose route passes through this station's internal lines
      const filtered = (_result.trip_stats || []).filter(ts =>
        (ts.route_line_ids || []).some(lid => lid.startsWith(sid + '.'))
      );

      if (filtered.length === 0) {
        setStatus(`No routes visit ${sid}`);
        return;
      }

      _stopReplay();
      setStatus(`Building focus: ${sid} (${filtered.length} routes)…`);

      // Build frames with only the filtered routes
      const focusResult = { ..._result, trip_stats: filtered };
      await _buildFrames(focusResult, _geojson);

      // Override speed: force 60× regardless of settings panel
      // so the user can actually watch individual pod movements.
      const origInterval = _replayIntervalMs();
      const slowInterval = Math.max(60, Math.round(1000 / 12 * 360 / 60));  // 60× speed

      _animTimer = setInterval(() => {
        if (_frameIdx >= _frames.length) _frameIdx = 0;
        _drawPods(_frames[_frameIdx].pods);
        _frameIdx++;
      }, slowInterval);

      document.getElementById("btn-replay").disabled = false;
      document.getElementById("btn-replay").textContent = "⏹ Stop";
      setStatus(`Watching ${sid} — ${filtered.length} route(s) at 60× — ▶▶ Replay to restore`);
    },

    // Restore full-network replay after focusStation
    async clearFocus() {
      if (!_result) return;
      _stopReplay();
      setStatus("Restoring full network…");
      await _buildFrames(_result, _geojson);
      document.getElementById("btn-replay").textContent = "▶▶ Replay";
      setStatus("Ready — press Replay to resume full network");
    },

    // Accessors for TimeMap (walk-ride-walk circles)
    getResult()  { return _result;  },
    getGeojson() { return _geojson; },

  };

})();
