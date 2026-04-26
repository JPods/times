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

  let _result     = null;
  let _frames     = [];    // [{pods: [{lat,lng,color}]}, ...]
  let _frameIdx   = 0;
  let _animTimer  = null;
  let _podMarkers = [];

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
    podList.forEach(({ lat, lng, color, label }) => {
      const icon = L.divIcon({
        className: "",
        html: `<div class="pod-marker" style="background:${color}" title="${label||''}"></div>`,
        iconSize: [8, 8],
        iconAnchor: [4, 4],
      });
      const m = L.marker([lat, lng], { icon, interactive: false });
      App.getLayers().pods.addLayer(m);
      _podMarkers.push(m);
    });
  }

  // Build animation frames from line_stats + network GeoJSON
  // Simple model: for each line with samples, animate one pod traversing it
  async function _buildFrames(result, geojson) {
    _frames = [];
    const lineFeatures = {};
    geojson.features
      .filter(f => f.properties.type === "line")
      .forEach(f => { lineFeatures[f.properties.line_id] = f; });

    const fps = 12;
    const totalFrames = fps * 10; // 10-second replay

    for (let frame = 0; frame < totalFrames; frame++) {
      const t = frame / totalFrames;
      const pods = [];

      result.line_stats.forEach(ls => {
        if (!ls.fleet_median_transit_ms) return;
        const feat = lineFeatures[ls.line_id];
        if (!feat) return;

        const coords = feat.geometry.coordinates; // [[lng,lat],...]
        if (coords.length < 2) return;

        // Ratio within this line's repeat cycle
        const cycleLen = ls.fleet_median_transit_ms / 1000 / 60; // fraction of replay
        const ratio = (t / Math.max(cycleLen, 0.001)) % 1;

        // Interpolate along coordinate chain
        const pos = _interpolateChain(coords, ratio);
        const speedRatio = Math.min(ratio * 2, 1); // ramp up
        pods.push({
          lat: pos[1], lng: pos[0],
          color: _podColor(speedRatio),
          label: ls.line_id,
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

  function _startReplay() {
    if (_animTimer) clearInterval(_animTimer);
    _frameIdx = 0;
    _animTimer = setInterval(() => {
      if (_frameIdx >= _frames.length) {
        _frameIdx = 0; // loop
      }
      _drawPods(_frames[_frameIdx].pods);
      _frameIdx++;
    }, 1000 / 12);
  }

  function _stopReplay() {
    if (_animTimer) { clearInterval(_animTimer); _animTimer = null; }
    _clearPods();
  }

  function _showResults(result) {
    _result = result;
    document.getElementById("panel-sim").style.display = "";
    const s = result.simulation || {};
    const pct = s.passengers_generated
      ? ((s.passengers_served / s.passengers_generated) * 100).toFixed(1)
      : "—";
    document.getElementById("sim-summary").innerHTML =
      `Passengers: ${s.passengers_served} / ${s.passengers_generated} (${pct}%)<br>
       Ticks: ${s.total_ticks}`;

    const sorted = [...(result.line_stats || [])]
      .filter(ls => ls.fleet_median_transit_ms)
      .sort((a, b) => (b.fleet_median_transit_ms - a.fleet_median_transit_ms));

    document.getElementById("sim-lines").innerHTML = sorted.map(ls =>
      `<div class="sim-line-row">
         <span class="line-id">${ls.line_id}</span>
         <span>${ls.length_m}m</span>
         <span>${Math.round(ls.fleet_median_transit_ms)} ms</span>
       </div>`
    ).join("");
  }

  return {

    async run() {
      const slots = parseInt(document.getElementById("sim-slots").value, 10) || 360;
      setStatus("Running simulation… ⏳");
      _stopReplay();

      const result = await api("POST", "/api/simulation/run", { slots });
      if (result.error) { alert(result.error); return; }

      _showResults(result);

      // Build animation frames
      const geojson = await api("GET", "/api/network");
      await _buildFrames(result, geojson);

      document.getElementById("btn-replay").disabled = false;
      const pax = result.simulation.passengers_served;
      const frameCount = _frames.length;
      console.log(`Simulation: ${pax} passengers served, ${frameCount} animation frames built`);
      setStatus(`Simulation complete — ${pax} passengers served`);

      // Auto-start animation if frames were built
      if (frameCount > 0) {
        _startReplay();
        document.getElementById("btn-replay").textContent = "⏹ Stop";
      }
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

  };

})();
