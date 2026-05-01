/**
 * settings.js — Simulation Settings panel.
 *
 * Opens as a sidebar panel (panel-settings).
 * Field choices match Java FormBuilder dropdowns.
 * Saves to GET/POST /api/settings (settings.json).
 */

"use strict";

const Settings = (() => {

  // Fields loaded/saved as plain numbers
  const _numFields = [
    "maxVelocityInKMPH",
    "accInG",
    "deccInG",
    "podLen",
    "minHeadwaySec",
    "podsPerStation",
    "graceDistance",
    "timeResolutionPerSec",
    "embarkingTimeInSec",
    "disembarkingTimeInSec",
    "ticketingTimeInSec",
    "stationEntryTimeInSec",
    "stationExitTimeInSec",
    "walkingSpeedKmh",
    "walkToStationSec",
    "walkFromStationSec",
    "simSpeedMultiplier",
    "stationLabelSize",
  ];

  function _applyDisplaySettings(data) {
    const size = data.stationLabelSize ?? 3;
    document.documentElement.style.setProperty("--station-label-size", size);
  }

  async function _load() {
    const data = await api("GET", "/api/settings");
    if (data.error) { console.warn("Settings load error:", data.error); return; }
    _numFields.forEach(k => {
      const el = document.getElementById(`cfg-${k}`);
      if (el && data[k] !== undefined) el.value = data[k];
    });
    _applyDisplaySettings(data);
  }

  return {

    async init() { await _load(); },

    togglePanel() {
      const panel = document.getElementById("panel-settings");
      if (!panel) return;
      if (panel.style.display === "none") {
        panel.style.display = "";
        _load();  // refresh values from server each time
      } else {
        panel.style.display = "none";
      }
    },

    async save() {
      const data = {};
      _numFields.forEach(k => {
        const el = document.getElementById(`cfg-${k}`);
        if (el) data[k] = parseFloat(el.value);
      });
      const r = await api("POST", "/api/settings", data);
      if (r && r.error) { alert("Settings save failed: " + r.error); return; }
      _applyDisplaySettings(data);
      setStatus("Settings saved");
    },

  };

})();

document.addEventListener("DOMContentLoaded", () => Settings.init());
