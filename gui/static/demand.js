/**
 * demand.js — Passenger demand editor (gravity model).
 *
 * Each station specifies:
 *   Departures/hr — how many passengers originate here per hour
 *   Arrivals/hr   — how attractive this station is as a destination
 *
 * The simulation distributes departures to destinations in proportion
 * to their arrival weights (gravity model).  No need to fill in every
 * O-D pair — rough approximations work well for planning.
 *
 * Default = 360 departures + 360 arrivals for all stations (uniform).
 */

"use strict";

const Demand = (() => {

  let _stationIds = [];
  let _config     = {};   // raw config from demand.json
  let _totalSlots = 360;  // max pax/hr any one station can generate

  const _short = id => id.replace(/^[A-Z]+_/, "").slice(-12);

  // ── Load from server ────────────────────────────────────────────────────────

  async function _load() {
    const data  = await api("GET", "/api/demand");
    _stationIds = data.station_ids || [];
    _config     = data.config      || {};
    _totalSlots = data.total_slots || 360;

    // Populate global pax/hr field
    const globalEl = document.getElementById("dmd-global-pax");
    if (globalEl) {
      const saved = _config.pax_per_hour;
      globalEl.value = (saved != null) ? saved : _totalSlots;
    }

    _buildTable();
  }

  // ── Build the simple per-station table ─────────────────────────────────────

  function _buildTable() {
    const wrap = document.getElementById("demand-table-wrap");
    if (!wrap) return;

    if (_stationIds.length < 2) {
      wrap.innerHTML =
        '<div style="color:#888;font-size:11px">Load a network with 2+ stations first.</div>';
      return;
    }

    const stCfg = _config.stations || {};

    let html = `
<table id="demand-tbl"
       style="border-collapse:collapse;font-size:11px;width:100%">
  <thead>
    <tr>
      <th style="text-align:left;color:#666;padding:2px 4px;background:#111;font-size:10px">Station</th>
      <th style="text-align:center;color:#5dade2;padding:2px 4px;background:#111;font-size:10px"
          title="Passengers generated here per hour">Departs/hr</th>
      <th style="text-align:center;color:#e67e22;padding:2px 4px;background:#111;font-size:10px"
          title="Attraction weight — how often other stations send passengers here">Arrives/hr</th>
    </tr>
  </thead>
  <tbody>`;

    let totalDep = 0, totalArr = 0;

    _stationIds.forEach(sid => {
      const sc  = stCfg[sid] || {};
      const dep = sc.departures != null ? sc.departures : _totalSlots;
      const arr = sc.arrivals   != null ? sc.arrivals   : _totalSlots;
      totalDep += dep;
      totalArr += arr;

      html += `
    <tr>
      <td title="${sid}"
          style="color:#aaa;padding:2px 4px;white-space:nowrap;
                 overflow:hidden;text-overflow:ellipsis;max-width:80px">
        ${_short(sid)}
      </td>
      <td style="padding:1px 3px;text-align:center">
        <input type="number" min="0" step="10"
               value="${dep}"
               data-sid="${sid}" data-field="departures"
               oninput="Demand._onInput(this)"
               style="width:54px;background:#1a2a3a;border:1px solid #3498db44;
                      color:#5dade2;font-size:11px;text-align:center;
                      border-radius:2px;padding:1px 2px">
      </td>
      <td style="padding:1px 3px;text-align:center">
        <input type="number" min="0" step="10"
               value="${arr}"
               data-sid="${sid}" data-field="arrivals"
               oninput="Demand._onInput(this)"
               style="width:54px;background:#2a1a0a;border:1px solid #e67e2244;
                      color:#e67e22;font-size:11px;text-align:center;
                      border-radius:2px;padding:1px 2px">
      </td>
    </tr>`;
    });

    html += `
  </tbody>
  <tfoot>
    <tr>
      <td style="color:#666;padding:3px 4px;font-size:10px;border-top:1px solid #333">
        Totals</td>
      <td id="dmd-total-dep"
          style="color:#5dade2;padding:3px;text-align:center;
                 font-size:10px;border-top:1px solid #333">
        ${totalDep}</td>
      <td id="dmd-total-arr"
          style="color:#e67e22;padding:3px;text-align:center;
                 font-size:10px;border-top:1px solid #333">
        ${totalArr}</td>
    </tr>
  </tfoot>
</table>`;

    html += _balanceNote(totalDep, totalArr);

    html += `
<div style="font-size:10px;color:#555;margin-top:6px;line-height:1.5">
  <b style="color:#777">Gravity model:</b> departures route to destinations
  in proportion to their arrivals weight.  Equal values = uniform spread.<br>
  360 pax/hr = one passenger every 10 sec.  No upper limit.
</div>`;

    wrap.innerHTML = html;
  }

  function _balanceNote(dep, arr) {
    if (!dep || !arr) return "";
    const ratio = dep / arr;
    const note  = ratio < 0.8 || ratio > 1.25
      ? `<span style="color:#e74c3c">&#9888; imbalanced (${ratio.toFixed(2)}×) — adjust arrivals to match departures</span>`
      : `<span style="color:#27ae60">&#10003; balanced</span>`;
    return `<div style="font-size:10px;margin-top:4px">
      ${dep} dep / ${arr} arr pax/hr — ${note}
    </div>`;
  }

  // ── Live update of totals row ───────────────────────────────────────────────

  function _refreshTotals() {
    let dep = 0, arr = 0;
    document.querySelectorAll("#demand-tbl input[data-field='departures']")
      .forEach(el => { dep += parseInt(el.value) || 0; });
    document.querySelectorAll("#demand-tbl input[data-field='arrivals']")
      .forEach(el => { arr += parseInt(el.value) || 0; });

    const depEl = document.getElementById("dmd-total-dep");
    const arrEl = document.getElementById("dmd-total-arr");
    if (depEl) depEl.textContent = dep;
    if (arrEl) arrEl.textContent = arr;

    // Replace balance note (the div right after the table)
    const wrap = document.getElementById("demand-table-wrap");
    if (wrap) {
      const noteEl = wrap.querySelector(".dmd-balance-note");
      if (noteEl) noteEl.outerHTML = _balanceNote(dep, arr).replace("<div", '<div class="dmd-balance-note"');
    }
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  return {

    async init()    { await _load(); },
    async refresh() { await _load(); },

    _onInput(input) { _refreshTotals(); },

    async save() {
      const globalPax = parseInt(document.getElementById("dmd-global-pax")?.value) || _totalSlots;
      const stations = {};
      document.querySelectorAll("#demand-tbl input[data-field]").forEach(el => {
        const sid   = el.dataset.sid;
        const field = el.dataset.field;
        const val   = parseInt(el.value) || 0;
        if (!stations[sid]) stations[sid] = {};
        stations[sid][field] = val;
      });

      const payload = { total_slots: _totalSlots, pax_per_hour: globalPax, stations };
      const r = await api("POST", "/api/demand", payload);
      if (r && r.ok) {
        setStatus("Demand saved — gravity model applied on next Run");
      } else {
        alert("Failed to save demand config.");
      }
    },

    togglePanel() {
      const panel = document.getElementById("panel-demand");
      if (!panel) return;
      if (panel.style.display === "none") {
        panel.style.display = "";
        _load();   // refresh each time panel opens (station list may have changed)
      } else {
        panel.style.display = "none";
      }
    },

  };

})();
