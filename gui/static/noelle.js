/**
 * noelle.js — Noelle Draft: data-driven station proposal
 *
 * Stations only — circles are the designer's job.
 * Highways are boundaries, not corridors.
 * Primary signal: crash rate on local arterials.
 * Secondary signal: AADT >= 5K on local roads.
 */

"use strict";

const Noelle = (() => {

  let _panel = null;

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
            'border-left:3px solid #3b82f6; margin-bottom:14px; white-space:pre-wrap; ' +
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

    // Placed count
    if (result.placed != null) {
      html += `<div style="background:#1a3a1a; padding:8px 12px; border-radius:4px; margin-bottom:12px">` +
              `Placed <strong>${result.placed}</strong> stations on the map. ` +
              `No circles — you add those where corridors branch.</div>`;
    }

    // Station list (top 15)
    const stations = result.stations || [];
    html += `<div style="margin-bottom:8px"><strong>Top Stations</strong> (${stations.length} total)</div>`;
    html += '<div style="max-height:200px; overflow-y:auto; font-size:11px; font-family:monospace">';
    for (let i = 0; i < Math.min(stations.length, 15); i++) {
      const s = stations[i];
      const icon = s.crashes >= 3 ? '<span style="color:#ef4444">&#9733;</span>' :
                   s.crashes >= 1 ? '<span style="color:#f59e0b">&#8226;</span>' : '&nbsp;';
      const aadt = s.aadt >= 1000 ? `${(s.aadt/1000).toFixed(1)}K` : `${s.aadt}`;
      html += `<div style="padding:2px 0">${icon} ${_esc(s.name)} — ${s.crashes} crashes, ${aadt} AADT</div>`;
    }
    if (stations.length > 15) {
      html += `<div style="color:#888; padding:4px 0">... ${stations.length - 15} more</div>`;
    }
    html += '</div>';

    // Actions
    html += '<div style="margin-top:14px; display:flex; gap:8px">';
    html += '<button onclick="Noelle.report()" style="flex:1; padding:6px; background:#2563eb; ' +
            'color:#fff; border:none; border-radius:4px; cursor:pointer">&#128196; Full Report</button>';
    html += '<button onclick="Noelle.closePanel()" style="flex:1; padding:6px; background:#444; ' +
            'color:#ddd; border:none; border-radius:4px; cursor:pointer">Close</button>';
    html += '</div>';

    el.innerHTML = html;
    document.body.appendChild(el);
    _panel = el;
  }

  function _esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function draft() {
    const ok = confirm(
      "Noelle will analyse AADT + accident data and place stations on the arterial grid.\n\n" +
      "Stations only — no circles (you add those).\n" +
      "Highways are boundaries, not corridors.\n\n" +
      "This creates a new network. Continue?"
    );
    if (!ok) return;

    // Flash message
    if (typeof App !== "undefined" && App.flash) {
      App.flash("Noelle is analysing...", 3000);
    }

    try {
      const r = await fetch("/api/noelle/draft?place=true", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const msg = err.error || r.statusText;
        if (msg.includes("No AADT") || msg.includes("No accident")) {
          alert("No traffic or crash data available for this area yet.\n\n" +
                "Noelle needs AADT and accident overlay data to propose stations. " +
                "Data must be pulled for this location first.");
        } else {
          alert("Noelle error: " + msg);
        }
        return;
      }
      const result = await r.json();
      _showPanel(result);

      // Reload the network display
      if (typeof App !== "undefined" && App.reload) {
        App.reload();
      } else {
        // Fallback: reload the page
        location.reload();
      }
    } catch (e) {
      alert("Noelle draft failed: " + e.message);
    }
  }

  function report() {
    window.open("/api/noelle/report", "_blank");
  }

  function closePanel() {
    if (_panel) { _panel.remove(); _panel = null; }
  }

  async function review() {
    // Generate Noelle's draft, embed in state, then download as .jpd
    try {
      setStatus("Noelle generating draft...");
      const r = await fetch("/api/noelle/review", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (err.error && err.error.includes("No overlay")) {
          if (typeof App !== "undefined" && App.flash) {
            App.flash("No overlay data for this area — Noelle cannot review yet.", 4000);
          }
          return;
        }
        setStatus("Noelle review: " + (err.error || r.statusText));
        return;
      }
      const result = await r.json();

      // Download Noelle's draft as a separate .jpd
      const dr = await fetch("/api/noelle/draft_jpd");
      if (dr.ok) {
        const blob = await dr.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "noelle_draft.jpd";
        a.click();
        URL.revokeObjectURL(url);
      }

      const msg = `Noelle draft saved (${result.noelle_stations} stations). ` +
                  `Open noelle_draft.jpd in a second tab to compare.`;
      setStatus(msg);
      if (typeof App !== "undefined" && App.flash) App.flash(msg, 5000);
    } catch (e) {
      console.warn("Noelle review failed:", e.message);
    }
  }

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

      // Show result
      const msg = result.summary || "Done";
      if (typeof App !== "undefined" && App.flash) App.flash(msg, 5000);
      setStatus(msg);

      // Reload display
      if (typeof App !== "undefined" && App.reload) {
        App.reload();
      } else {
        location.reload();
      }
    } catch (e) {
      alert("Noelle refine failed: " + e.message);
    }
  }

  return { draft, refine, report, review, closePanel };
})();
