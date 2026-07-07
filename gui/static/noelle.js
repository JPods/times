/**
 * noelle.js — Noelle network design agent
 *
 * Draft = toggleable overlay layer (does not modify network)
 * Apply = place draft stations into the actual network
 * Refine = prune no-signal stations, add missing-signal stations
 * Report = printable analysis in new tab
 */

"use strict";

const Noelle = (() => {

  let _panel = null;
  let _draftLayer = null;    // Leaflet layer group for draft overlay
  let _draftData = null;     // cached draft result from server
  let _draftVisible = false;

  function _esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Draft as toggle layer ─────────────────────────────────────────────────

  async function draft() {
    const m = App.getMap();

    // Toggle off if already visible
    if (_draftVisible && _draftLayer) {
      m.removeLayer(_draftLayer);
      _draftLayer = null;
      _draftVisible = false;
      setStatus("Noelle draft layer off");
      closePanel();
      return;
    }

    setStatus("Noelle analysing...");

    try {
      // Fetch draft analysis without placing structures
      const r = await fetch("/api/noelle/draft", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const msg = err.error || r.statusText;
        if (msg.includes("No AADT") || msg.includes("No accident")) {
          alert("No traffic or crash data available for this area yet.\n\n" +
                "Noelle needs AADT and accident overlay data to propose stations.\n" +
                "Data must be pulled for this location first.");
        } else {
          alert("Noelle: " + msg);
        }
        return;
      }

      _draftData = await r.json();
      const stations = _draftData.stations || [];

      // Build overlay layer — green diamonds for proposed stations
      _draftLayer = L.layerGroup();
      for (const s of stations) {
        const size = s.crashes >= 3 ? 20 : (s.crashes >= 1 ? 16 : 12);
        const color = s.crashes >= 3 ? "#9333ea" : (s.crashes >= 1 ? "#a855f7" : "#c084fc");
        const marker = L.circleMarker([s.lat, s.lon], {
          radius: size,
          color: color,
          fillColor: color,
          fillOpacity: 0.5,
          weight: 2,
        });
        const aadt = s.aadt >= 1000 ? `${(s.aadt/1000).toFixed(1)}K` : `${s.aadt}`;
        marker.bindTooltip(
          `<b>Noelle proposal</b><br>${s.crashes} crashes, ${aadt} AADT<br>${s.name}`,
          { sticky: true }
        );
        _draftLayer.addLayer(marker);
      }

      _draftLayer.addTo(m);
      _draftVisible = true;
      setStatus(`Noelle draft: ${stations.length} stations (green layer)`);

      _showPanel(_draftData);

    } catch (e) {
      alert("Noelle draft failed: " + e.message);
    }
  }

  // ── Apply draft to network ────────────────────────────────────────────────

  async function apply() {
    if (!_draftData || !_draftData.stations || !_draftData.stations.length) {
      alert("No draft to apply. Click Draft first to generate Noelle's proposal.");
      return;
    }

    const count = _draftData.stations.length;
    const ok = confirm(
      `Place ${count} of Noelle's proposed stations into the network?\n\n` +
      "Stations only — no circles. This modifies your network."
    );
    if (!ok) return;

    try {
      const r = await fetch("/api/noelle/draft?place=true", { method: "POST" });
      if (!r.ok) {
        alert("Apply failed");
        return;
      }
      const result = await r.json();

      // Remove the draft overlay — stations are now real
      if (_draftLayer) {
        App.getMap().removeLayer(_draftLayer);
        _draftLayer = null;
        _draftVisible = false;
      }

      const msg = `Applied: ${result.placed || 0} stations placed`;
      setStatus(msg);
      if (typeof App !== "undefined" && App.flash) App.flash(msg, 3000);

      // Reload network display
      if (typeof App !== "undefined" && App.reload) {
        App.reload();
      } else {
        location.reload();
      }
    } catch (e) {
      alert("Apply failed: " + e.message);
    }
  }

  // ── Refine existing network ───────────────────────────────────────────────

  async function refine() {
    const ok = confirm(
      "Noelle will refine the current network:\n\n" +
      "• Prune stations with no crash or traffic signal\n" +
      "• Add stations where data shows signal but no structure exists\n" +
      "• Circles are never touched — those are yours\n\n" +
      "Continue?"
    );
    if (!ok) return;

    if (typeof App !== "undefined" && App.flash) {
      App.flash("Noelle refining...", 3000);
    }

    try {
      const r = await fetch("/api/noelle/refine", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert("Noelle refine: " + (err.error || r.statusText));
        return;
      }
      const result = await r.json();
      const msg = result.summary || "Done";
      if (typeof App !== "undefined" && App.flash) App.flash(msg, 5000);
      setStatus(msg);

      if (typeof App !== "undefined" && App.reload) {
        App.reload();
      } else {
        location.reload();
      }
    } catch (e) {
      alert("Noelle refine failed: " + e.message);
    }
  }

  // ── Report ────────────────────────────────────────────────────────────────

  function report() {
    window.open("/api/noelle/report", "_blank");
  }

  // ── Panel ─────────────────────────────────────────────────────────────────

  function _showPanel(result) {
    if (_panel) { _panel.remove(); _panel = null; }

    const el = document.createElement("div");
    el.id = "noelle-panel";
    el.style.cssText =
      "position:fixed; top:60px; right:20px; width:420px; max-height:80vh; " +
      "overflow-y:auto; background:#1a1a2e; color:#e0e0e0; " +
      "border:1px solid #444; border-radius:8px; padding:16px; " +
      "font-size:13px; z-index:10000; box-shadow:0 4px 20px rgba(0,0,0,0.5);";

    let html = '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">';
    html += '<strong style="font-size:15px">Noelle Draft</strong>';
    html += '<button onclick="Noelle.closePanel()" style="background:none; border:none; color:#aaa; cursor:pointer; font-size:18px">&times;</button>';
    html += '</div>';

    // Summary
    html += '<div style="background:#232340; padding:10px 12px; border-radius:6px; ' +
            'border-left:3px solid #10b981; margin-bottom:14px; white-space:pre-wrap; ' +
            'font-family:inherit; line-height:1.5">';
    html += _esc(result.summary);
    html += '</div>';

    // Crash rate table
    if (result.crash_rate_summary && result.crash_rate_summary.length) {
      html += '<div style="margin-bottom:12px"><strong>Crashes / 10K AADT</strong>';
      html += '<table style="width:100%; border-collapse:collapse; margin-top:6px; font-size:12px">';
      html += '<tr style="border-bottom:1px solid #444"><th style="text-align:left; padding:4px">Type</th>' +
              '<th style="text-align:right; padding:4px">Crashes</th>' +
              '<th style="text-align:right; padding:4px">Ped</th>' +
              '<th style="text-align:right; padding:4px">Rate</th></tr>';
      for (const cr of result.crash_rate_summary) {
        const hot = cr.rate_per_10k > 20 ? ' style="background:#3b1515"' : '';
        html += `<tr${hot}><td style="padding:3px 4px">${_esc(cr.type)}</td>` +
                `<td style="text-align:right; padding:3px 4px">${cr.crashes}</td>` +
                `<td style="text-align:right; padding:3px 4px">${cr.ped_crashes}</td>` +
                `<td style="text-align:right; padding:3px 4px; font-weight:600">${cr.rate_per_10k}</td></tr>`;
      }
      html += '</table></div>';
    }

    // Station count
    const stations = result.stations || [];
    html += `<div style="background:#1a2e1a; padding:8px 12px; border-radius:4px; margin-bottom:12px">` +
            `<strong>${stations.length}</strong> proposed stations shown as green layer. ` +
            `Click <strong>Apply Draft</strong> to place them, or toggle Draft off to hide.</div>`;

    // Top stations
    html += `<div style="margin-bottom:8px"><strong>Top Stations</strong></div>`;
    html += '<div style="max-height:180px; overflow-y:auto; font-size:11px; font-family:monospace">';
    for (let i = 0; i < Math.min(stations.length, 15); i++) {
      const s = stations[i];
      const icon = s.crashes >= 3 ? '<span style="color:#10b981">&#9733;</span>' :
                   s.crashes >= 1 ? '<span style="color:#34d399">&#8226;</span>' : '&nbsp;';
      const aadt = s.aadt >= 1000 ? `${(s.aadt/1000).toFixed(1)}K` : `${s.aadt}`;
      html += `<div style="padding:2px 0">${icon} ${_esc(s.name)} — ${s.crashes} crashes, ${aadt} AADT</div>`;
    }
    if (stations.length > 15) {
      html += `<div style="color:#888; padding:4px 0">... ${stations.length - 15} more</div>`;
    }
    html += '</div>';

    // Actions
    html += '<div style="margin-top:14px; display:flex; gap:8px">';
    html += '<button onclick="Noelle.apply()" style="flex:1; padding:6px; background:#10b981; ' +
            'color:#fff; border:none; border-radius:4px; cursor:pointer">&#10003; Apply Draft</button>';
    html += '<button onclick="Noelle.report()" style="flex:1; padding:6px; background:#2563eb; ' +
            'color:#fff; border:none; border-radius:4px; cursor:pointer">&#128196; Report</button>';
    html += '<button onclick="Noelle.closePanel()" style="flex:1; padding:6px; background:#444; ' +
            'color:#ddd; border:none; border-radius:4px; cursor:pointer">Close</button>';
    html += '</div>';

    el.innerHTML = html;
    document.body.appendChild(el);
    _panel = el;
  }

  function closePanel() {
    if (_panel) { _panel.remove(); _panel = null; }
  }

  return { draft, apply, refine, report, closePanel };
})();
