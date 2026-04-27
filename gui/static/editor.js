/**
 * editor.js — Network editing tools
 * Place stations (full structure), switches, traffic circles.
 * Draw directed lines between nodes.
 * Shift-click on a line      → add a draggable waypoint
 * Ctrl/Cmd-click on a line   → break (delete) the line
 * Shift-click on a node      → remove the node
 * Auto-connect (best-effort MST).
 */

"use strict";

const Editor = (() => {

  let _mode           = null;  // null | 'station' | 'switch' | 'circle' | 'line'
  let _lineStart      = null;  // {node_id, lat, lng} for first click of line draw
  let _heading        = 0;     // heading for next station placement
  let _circleRotation = 0;     // arm rotation for next circle (0 or 45)

  // All buttons that can be "active" (one at a time)
  const _allBtns = [
    "btn-add-station", "btn-waypoint", "btn-add-circle", "btn-add-circle45",
    "btn-draw-line", "btn-autoconnect",
    "btn-st-ns", "btn-st-ew", "btn-st-nesw", "btn-st-nwse",
  ];

  function _setMode(mode, activeBtn) {
    _allBtns.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove("active");
    });
    _mode      = mode;
    _lineStart = null;
    if (activeBtn) {
      const el = document.getElementById(activeBtn);
      if (el) el.classList.add("active");
    }
    const hdgLabel = mode === "station" ? ` (${_heading}°)` : "";
    const labels = {
      station: `Click map to place station${hdgLabel}`,
      waypoint: "Click on a guideway to place a waypoint — drag to route both guideways around terrain",
      circle:  "Click map to place traffic circle",
      line:    "Click first node, then second node",
    };
    setStatus(labels[mode] || "Ready");
    App.getMap().getContainer().style.cursor = mode ? "crosshair" : "";
  }

  // Map click handler — place node or finish line
  App.getMap().on("click", async (e) => {
    if (!_mode) return;
    const { lat, lng } = e.latlng;

    if (_mode === "waypoint") {
      // Handled by mousedown/mouseup drag system in app.js — nothing to do here
      return;
    }

    if (_mode === "station") {
      const r = await api("POST", "/api/network/station",
                          { lat, lon: lng, heading_deg: _heading });
      if (r.error) { alert(r.error); return; }
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
      setStatus(`Placed station ${r.station_id} (${r.cp_ids.length} CPs)`);
    }

    if (_mode === "circle") {
      const rot  = _circleRotation;
      const arms = [0, 90, 180, 270].map(h => (h + rot) % 360);
      const r = await api("POST", "/api/network/circle", { lat, lon: lng, arm_headings: arms });
      if (r.error) { alert(r.error); return; }
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
      const label = rot === 0 ? "N/E/S/W" : "NE/SE/SW/NW";
      setStatus(`Placed traffic circle ${r.circle_id} — arms ${label}`);
    }

    if (_mode === "line") {
      // Line mode requires clicking on nodes, not empty map
    }
  });

  function _addTempNode(nid, lat, lng, type) {
    // Mimics what _addNodeFeature does in app.js
    const icon = L.divIcon({
      className: type === "station" ? "node-marker-station" : "node-marker-switch",
      iconSize: null,
    });
    const marker = L.marker([lat, lng], { icon });
    marker.bindTooltip(nid, { direction: "top", offset: [0, -6] });
    marker.on("click", (e) => {
      if (e.originalEvent.shiftKey) {
        Editor.removeNode(nid);
      } else if (Editor.isDrawingLine()) {
        Editor.lineNodeClick(nid, lat, lng);
      }
    });
    App.getLayers().nodes.addLayer(marker);
    App.getNodeMap()[nid] = marker;
  }

  function _guardRO() {
    if (!App.isReadOnly()) return false;
    setStatus("Network locked — click \uD83D\uDD13 Edit to modify");
    return true;
  }

  return {

    startPlace(type, heading) {
      if (_guardRO()) return;
      if (type === "station" && heading !== undefined) {
        _heading = heading;
        const inp = document.getElementById("station-heading");
        if (inp) inp.value = heading;
      }
      // Determine which palette button to highlight
      if (type === "circle" && heading !== undefined) {
        _circleRotation = heading;
      }
      const btnMap = {
        switch: "btn-add-switch",
        circle: _circleRotation === 45 ? "btn-add-circle45" : "btn-add-circle",
      };
      const headingBtnMap = { 0: "btn-st-ns", 90: "btn-st-ew", 45: "btn-st-nesw", 135: "btn-st-nwse" };
      const activeBtn = type === "station"
        ? (headingBtnMap[_heading] || "btn-add-station")
        : btnMap[type];
      _setMode(_mode === type && (type !== "circle" || _circleRotation === (heading ?? 0)) ? null : type, activeBtn);
    },

    startWaypoint() {
      if (_guardRO()) return;
      _setMode(_mode === "waypoint" ? null : "waypoint", "btn-waypoint");
    },

    isWaypointing() {
      return _mode === "waypoint";
    },

    startDrawLine() {
      if (_guardRO()) return;
      _setMode(_mode === "line" ? null : "line", "btn-draw-line");
    },

    isDrawingLine() {
      return _mode === "line";
    },

    async lineNodeClick(nid, lat, lng) {
      if (!_lineStart) {
        _lineStart = { node_id: nid, lat, lng };
        App.getNodeMap()[nid]?.setOpacity?.(0.5);
        setStatus(`Line start: ${nid} — now click end node`);
        return;
      }

      if (_lineStart.node_id === nid) {
        setStatus("Same node — pick a different end node");
        return;
      }

      const r = await api("POST", "/api/network/line", {
        start_node: _lineStart.node_id,
        end_node: nid,
      });
      // Restore opacity
      App.getNodeMap()[_lineStart.node_id]?.setOpacity?.(1);
      _lineStart = null;

      if (r.error) { alert(r.error); return; }

      // Add line to map
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
      setStatus(`Line added (${r.length_m} m)`);
    },

    async breakLine(lineId) {
      if (_guardRO()) return;
      const r = await api("DELETE", `/api/network/line/${lineId}`);
      if (r.error) { alert(r.error); return; }
      // Re-render so both lines and CP state update correctly
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
      setStatus(`Removed guideway pair (${(r.broken || []).length} lines)`);
    },

    async removeNode(nid) {
      if (_guardRO()) return;
      const r = await api("DELETE", `/api/network/node/${nid}`);
      if (r.error) { alert(r.error); return; }
      // Remove marker
      const mk = App.getNodeMap()[nid];
      if (mk) App.getLayers().nodes.removeLayer(mk);
      delete App.getNodeMap()[nid];
      // Remove affected lines
      (r.lines_removed || []).forEach(lid => {
        const pl = App.getLineMap()[lid];
        if (pl) App.getLayers().lines.removeLayer(pl);
        delete App.getLineMap()[lid];
      });
      setStatus(`Removed ${nid}`);
    },

    async autoConnect() {
      if (_guardRO()) return;
      setStatus("Auto-connecting… ⏳");
      const r = await api("POST", "/api/network/autoconnect");
      if (r.error) { alert(r.error); return; }
      // Re-render to show new lines
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
      const skipped = r.skipped_outer ? r.skipped_outer.length : 0;
      const skipMsg = skipped ? `  ·  ${skipped} outer CPs left open` : "";
      setStatus(`Auto-connected: ${r.count} lines added${skipMsg}`);
    },

    escape() {
      _setMode(null);
    },

    getMode() {
      return _mode;
    },
  };

})();

// Keyboard shortcuts
document.addEventListener("keydown", (e) => {
  if (document.activeElement && document.activeElement.tagName === "INPUT") return;

  // Escape — close any open dialog first, then cancel tools
  if (e.key === "Escape") {
    const backdrop = document.getElementById("grid-dialog-backdrop");
    if (backdrop && backdrop.style.display !== "none") { Grid.closeDialog(); return; }
    if (typeof TimeMap !== "undefined") TimeMap.deactivate();
    if (typeof wptCancel === "function") wptCancel();
    Editor.escape();
    if (typeof _clearSelection === "function") _clearSelection();
    if (typeof _selectedCpId !== "undefined" && _selectedCpId !== null) {
      _selectedCpId = null;
      setStatus("Ready");
    }
    if (typeof _selectedNodeId !== "undefined" && _selectedNodeId !== null) {
      _selectedNodeId = null;
    }
    if (typeof _selectedStructSid !== "undefined" && _selectedStructSid !== null) {
      _selectedStructSid = null;
      setStatus("Ready");
    }
  }

  // Delete / Backspace
  if (e.key === "Delete" || e.key === "Backspace") {
    if (App.isReadOnly()) { setStatus("Network locked — click \uD83D\uDD13 Edit to modify"); return; }
    // Region selection takes priority
    if (typeof _sel !== "undefined" &&
        (_sel.structures.size + _sel.freeNodes.size) > 0) {
      deleteSelection();
      return;
    }
    // CP selected — delete its parent structure
    if (typeof _selectedCpId !== "undefined" && _selectedCpId !== null) {
      const cpProps = typeof _cpPropsMap !== "undefined" && _cpPropsMap[_selectedCpId];
      const sid = cpProps && cpProps.structure_id;
      _selectedCpId = null;
      if (sid) {
        api("DELETE", `/api/network/structure/${sid}`).then(() => {
          api("GET", "/api/network").then(gj => { App._render(gj); setStatus(`Deleted ${sid}`); });
        });
      }
      return;
    }

    // Single structure selected (click on internal line or CP area)
    if (typeof _selectedStructSid !== "undefined" && _selectedStructSid !== null) {
      const sid = _selectedStructSid;
      _selectedStructSid = null;
      api("DELETE", `/api/network/structure/${sid}`).then(() => {
        api("GET", "/api/network").then(gj => { App._render(gj); setStatus(`Deleted ${sid}`); });
      });
      return;
    }
    // Single node selected
    if (typeof _selectedNodeId !== "undefined" && _selectedNodeId !== null) {
      const nid = _selectedNodeId;
      _selectedNodeId = null;
      Editor.removeNode(nid);
    }
  }
});
