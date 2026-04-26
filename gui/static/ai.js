/**
 * ai.js — Allie AI network recommendation panel
 *
 * Sends network parameters to Allie via the server's /api/ai/recommend endpoint.
 * Allie returns candidate network suggestions as GeoJSON + explanation text.
 * User can accept a suggestion to load it as the working network.
 *
 * As Allie accumulates simulation results and trip data, recommendations improve.
 */

"use strict";

const AI = (() => {

  let _visible = false;
  let _lastSuggestion = null;

  return {

    togglePanel() {
      _visible = !_visible;
      document.getElementById("panel-allie").style.display = _visible ? "" : "none";
      setStatus(_visible ? "Allie panel open" : "Allie panel closed");
    },

    async recommend() {
      const params = {
        max_stations:    parseInt(document.getElementById("ai-stations").value, 10),
        budget_km:       parseFloat(document.getElementById("ai-budget").value),
        speed_kmh:       parseFloat(document.getElementById("ai-speed").value),
        map_bounds:      App.getMap().getBounds(),
      };

      document.getElementById("allie-response").innerHTML =
        '<span class="spinner"></span> Asking Allie…';

      const r = await api("POST", "/api/ai/recommend", params);

      if (r.error) {
        document.getElementById("allie-response").textContent = `Error: ${r.error}`;
        return;
      }

      _lastSuggestion = r;

      let html = `<b>${r.summary || "Recommendation"}</b>\n\n${r.explanation || ""}`;
      if (r.options && r.options.length) {
        html += "\n\nOptions:\n";
        r.options.forEach((opt, i) => {
          html += `\n${i+1}. ${opt.label} — ${opt.reason}`;
        });
      }
      if (r.network) {
        html += `\n\n<button onclick="AI.acceptSuggestion()">Accept this network</button>`;
      }
      document.getElementById("allie-response").innerHTML = html;
    },

    async acceptSuggestion() {
      if (!_lastSuggestion || !_lastSuggestion.network) return;
      const r = await api("POST", "/api/network/load_suggestion", {
        network: _lastSuggestion.network,
      });
      if (r.error) { alert(r.error); return; }
      App._render(r);
      setStatus("Loaded Allie's suggested network");
    },

  };

})();
