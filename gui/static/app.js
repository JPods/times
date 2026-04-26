/**
 * app.js — Route-Time main application
 * Initialises the Leaflet map, loads/saves networks, coordinates modules.
 */

"use strict";

// ── Map setup ────────────────────────────────────────────────────────────────

const TILES = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>',
    maxZoom: 19,
  },
  satellite: {
    url: "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr: "&copy; Google",
    maxZoom: 21,
  },
  topo: {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
    maxZoom: 17,
  },
  dark: {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attr: '&copy; <a href="https://carto.com">CARTO</a>',
    maxZoom: 19,
  },
};

// Restore saved view, or fall back to default
const _savedView = (() => {
  try { return JSON.parse(localStorage.getItem("rt_map_view")); } catch { return null; }
})();
const map = L.map("map", { zoomControl: true }).setView(
  _savedView ? [_savedView.lat, _savedView.lng] : [37.31, -121.87],
  _savedView ? _savedView.zoom : 13
);

// Persist view whenever the user pans or zooms
map.on("moveend zoomend", () => {
  const c = map.getCenter();
  localStorage.setItem("rt_map_view", JSON.stringify(
    { lat: c.lat, lng: c.lng, zoom: map.getZoom() }
  ));
});

let _currentTileLayer = null;

const Map = {
  setTiles(key) {
    if (_currentTileLayer) map.removeLayer(_currentTileLayer);
    const t = TILES[key] || TILES.osm;
    _currentTileLayer = L.tileLayer(t.url, { attribution: t.attr, maxZoom: t.maxZoom });
    _currentTileLayer.addTo(map);
  },
};

Map.setTiles("osm");

// ── JPods logo watermark (bottom-right of map) ────────────────────────────────
const _logoControl = L.control({ position: "bottomright" });
_logoControl.onAdd = () => {
  const div = L.DomUtil.create("div", "jpods-logo-control");
  const img = L.DomUtil.create("img", "", div);
  img.src = "/static/jpods-logo.png";
  img.alt = "JPods";
  img.title = "JPods® — Solar-Powered Personal Transit";
  L.DomEvent.disableClickPropagation(div);
  return div;
};
_logoControl.addTo(map);

// ── Walk-Ride-Walk ledger (bottom-left, always visible) ───────────────────────
const _ledgerControl = L.control({ position: "bottomleft" });
_ledgerControl.onAdd = () => {
  const div = L.DomUtil.create("div", "wrw-ledger");
  div.innerHTML =
    `<div class="wrw-ledger-title">Walk · Ride · Walk</div>` +
    [
      [5,  "#00ff44", "#00aa00", "5 min"],
      [10, "#4488ff", "#0044cc", "10 min"],
      [20, "#ffff00", "#aaaa00", "20 min"],
      [30, "#ff6644", "#cc2200", "30 min"],
    ].map(([, fill, stroke, label]) =>
      `<div class="wrw-row">` +
      `<span class="wrw-swatch" style="background:${fill};border-color:${stroke}"></span>` +
      `<span class="wrw-label">${label}</span>` +
      `</div>`
    ).join("") +
    `<div class="wrw-hint">&#9711; Coverage → click map</div>`;
  L.DomEvent.disableClickPropagation(div);
  return div;
};
_ledgerControl.addTo(map);

// Coordinate display
map.on("mousemove", (e) => {
  document.getElementById("status-coord").textContent =
    `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`;
});

// ── Network layers ────────────────────────────────────────────────────────────

const _layers = {
  lines:     L.layerGroup().addTo(map),
  nodes:     L.layerGroup().addTo(map),
  waypoints: L.layerGroup().addTo(map),
  pods:      L.layerGroup().addTo(map),
  timemap:   L.layerGroup().addTo(map),   // walk-ride-walk coverage circles
};

// Keyed by feature id → Leaflet layer
const _lineMap          = {};
const _nodeMap          = {};
const _partnerMap       = {};  // line_id → partner_line_id (for paired guideway movement)
const _cpPropsMap       = {};  // cp_id → CP properties (for region-select)
const _lineStructMap     = {};  // line_id → structure_id (derived from metadata.structures)
const _structureMetaMap  = {};  // structure_id → {line_ids, node_ids, …} from server metadata
const _structureLayerMap = {};  // structure_id → L.layerGroup holding all internal polylines
const _lineNodeMap       = {};  // line_id → {s: startNodeId, e: endNodeId}

// Set true before _render when loading a file — causes a one-time fit-to-bounds
let _fitOnNextRender = false;

// ── Region selection (Shift+drag) ─────────────────────────────────────────────
// Overrides Leaflet's built-in box-zoom so Shift+drag selects instead of zooms.
map.boxZoom.disable();

const _sel = {
  active:          false,
  start:           null,
  rect:            null,
  structures:      new Set(),   // structure_ids in current selection
  freeNodes:       new Set(),   // node_ids (non-structure) in current selection
  origLineStyles:  {},          // lid → {color, opacity, weight} before highlight
};

// Capture-phase shift+mousedown — intercepts clicks on markers too, so
// drag-select works regardless of where in the map the drag starts.
map.getContainer().addEventListener("mousedown", (e) => {
  if (!e.shiftKey) return;
  if (Editor.getMode() !== null) return;
  if (_moveState.active) return;
  e.preventDefault();
  e.stopPropagation();
  map.dragging.disable();
  _sel.active = true;
  _sel.start  = map.mouseEventToLatLng(e);
  _sel.rect   = null;
}, { capture: true });

map.on("mousemove", (e) => {
  if (!_sel.active) return;
  const bounds = L.latLngBounds(_sel.start, e.latlng);
  if (_sel.rect) {
    _sel.rect.setBounds(bounds);
  } else {
    _sel.rect = L.rectangle(bounds, {
      color: "#f1c40f", weight: 1.5, dashArray: "4 3",
      fillOpacity: 0.08, interactive: false,
    }).addTo(map);
  }
});

map.on("mouseup", (e) => {
  if (!_sel.active) return;
  _sel.active = false;
  map.dragging.enable();
  if (!_sel.rect) return;           // was a plain shift-click, not a drag

  const bounds = _sel.rect.getBounds();
  map.removeLayer(_sel.rect);
  _sel.rect = null;
  _selectInBounds(bounds);
});

function _selectInBounds(bounds) {
  _sel.structures.clear();
  _sel.freeNodes.clear();

  // Structures: any CP inside the box captures the whole structure
  Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
    const mk = _nodeMap[cpId];
    if (!mk) return;
    if (bounds.contains(mk.getLatLng())) {
      _sel.structures.add(props.structure_id);
    }
  });

  // Also capture by any internal line vertex — catches large stations
  // where the CPs are outside the rubber-band but the body is inside.
  Object.entries(_lineStructMap).forEach(([lid, sid]) => {
    if (_sel.structures.has(sid)) return;  // already captured
    const pl = _lineMap[lid];
    if (!pl) return;
    if (pl.getLatLngs().some(ll => bounds.contains(ll))) {
      _sel.structures.add(sid);
    }
  });

  // Free nodes (non-CP, non-internal)
  Object.entries(_nodeMap).forEach(([nid, mk]) => {
    if (_cpPropsMap[nid]) return;   // skip CP markers already handled
    if (bounds.contains(mk.getLatLng())) {
      _sel.freeNodes.add(nid);
    }
  });

  const n = _sel.structures.size + _sel.freeNodes.size;
  if (n === 0) { setStatus("Ready"); return; }

  // Highlight selected CP markers (orange glow via cp-hit-selected class)
  Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
    const mk = _nodeMap[cpId];
    if (!mk) return;
    mk.setIcon(_cpIcon(props, _sel.structures.has(props.structure_id)));
  });
  // Highlight selected free nodes
  Object.entries(_nodeMap).forEach(([nid, mk]) => {
    if (_cpPropsMap[nid]) return;
    if (_sel.freeNodes.has(nid)) mk.setOpacity(0.4);
  });

  // Highlight internal lines of selected structures (save originals first)
  _sel.origLineStyles = {};
  Object.entries(_lineStructMap).forEach(([lid, sid]) => {
    if (!_sel.structures.has(sid)) return;
    const pl = _lineMap[lid];
    if (!pl) return;
    const s = pl.options;
    _sel.origLineStyles[lid] = { color: s.color, opacity: s.opacity, weight: s.weight };
    pl.setStyle({ color: "#f39c12", opacity: 1, weight: 4 });
  });

  setStatus(`${n} item(s) selected — Delete to remove  ·  Esc to cancel`);
}

function _clearSelection() {
  // Remove selection highlights from CP markers
  Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
    const mk = _nodeMap[cpId];
    if (mk) mk.setIcon(_cpIcon(props, cpId === _selectedCpId));
  });
  // Remove highlights from free nodes
  Object.entries(_nodeMap).forEach(([nid, mk]) => {
    if (!_cpPropsMap[nid]) mk.setOpacity(1);
  });
  // Restore original line styles
  Object.entries(_sel.origLineStyles).forEach(([lid, style]) => {
    _lineMap[lid]?.setStyle(style);
  });
  _sel.origLineStyles = {};

  _sel.structures.clear();
  _sel.freeNodes.clear();
  if (_sel.rect) { map.removeLayer(_sel.rect); _sel.rect = null; }
}

// ── Alt+drag structure move ───────────────────────────────────────────────────
// Strategy: intercept mousedown in document capture phase (before Leaflet's
// drag handler ever sees it) when the cursor is hovering over a CP marker.
// This prevents the map from panning during the move.

const _moveState = {
  active:      false,
  sid:         null,
  startLatlng: null,
  origPos:     {},   // cpId → L.LatLng snapshot at drag start
  connectors:  [],   // [{lid, endIdx, origLatlng}] connector lines whose endpoint moves
};

let _hoverStructSid = null;   // CP or structure-line under cursor → triggers structure move
let _hoverLineId    = null;   // free guideway under cursor → triggers inline bend drag

// Show circle cursor whenever Alt is held over the map — signals "grab radius active"
document.addEventListener("keydown", (e) => {
  if (e.key === "Alt" && !e.repeat) {
    map.getContainer().classList.add("alt-grab-mode");
    e.preventDefault();   // suppress browser menu-bar activation (Windows/Linux)
  }
});
document.addEventListener("keyup", (e) => {
  if (e.key === "Alt") {
    map.getContainer().classList.remove("alt-grab-mode");
  }
});
// Also clear if window loses focus mid-drag
window.addEventListener("blur", () => {
  map.getContainer().classList.remove("alt-grab-mode");
});

// ── Inline guideway-bend drag state ──────────────────────────────────────────
const _bendState = {
  active:     false,
  mode:       null,    // 'new' | 'existing'
  // mode === 'new': inserting a fresh bend point
  segIdxMap:  {},      // lid → inserted point index
  origLls:    {},      // lid → LatLng[] snapshot
  tempMk:     null,
  // mode === 'existing': dragging an existing handle pair
  handle:     null,    // the waypoint marker being dragged
  exLid:      null,
  exPid:      null,
  exIdx:      null,
};

const _GRAB_RADIUS_PX = 36;  // 60% of original 60px

// All free-guideway lines within _GRAB_RADIUS_PX of latlng (skips structure internals).
function _freeGuideywaysNear(latlng) {
  const layerPt = map.latLngToLayerPoint(latlng);
  const hits = [];
  Object.entries(_lineMap).forEach(([lid, pl]) => {
    if (_lineStructMap[lid]) return;
    const cp = pl.closestLayerPoint(layerPt);
    if (cp && cp.distance <= _GRAB_RADIUS_PX) hits.push(lid);
  });
  return hits;
}

// Nearest existing waypoint handle within _GRAB_RADIUS_PX, or null.
function _nearestWaypointHandle(latlng) {
  const layerPt = map.latLngToLayerPoint(latlng);
  let best = null, bestDist = Infinity;
  _layers.waypoints.eachLayer(mk => {
    if (!mk._wptData) return;   // skip temp markers (no metadata)
    const mpt = map.latLngToLayerPoint(mk.getLatLng());
    const d   = layerPt.distanceTo(mpt);
    if (d <= _GRAB_RADIUS_PX && d < bestDist) { bestDist = d; best = mk; }
  });
  return best;
}

// Capture-phase mousedown — intercepts Alt+mousedown before Leaflet's drag handler.
// Branches on what the cursor is hovering:
//   _hoverStructSid → move the whole structure
//   _hoverLineId    → inline bend-point drag on that guideway pair
document.addEventListener("mousedown", (e) => {
  if (!e.altKey) return;
  if (!map.getContainer().contains(e.target)) return;
  if (!_hoverStructSid && !_hoverLineId) return;

  e.preventDefault();
  e.stopPropagation();

  const latlng = map.mouseEventToLatLng(e);

  // ── Branch A: structure move ───────────────────────────────────────────
  if (_hoverStructSid) {
    const sid = _hoverStructSid;
    _moveState.origPos = {};
    Object.entries(_cpPropsMap).forEach(([cpId, p]) => {
      if (p.structure_id !== sid) return;
      const mk = _nodeMap[cpId];
      if (mk) _moveState.origPos[cpId] = mk.getLatLng();
    });

    // Collect connector line endpoints that belong to this structure's CPs
    // so they can follow the drag live.
    const movingTips = new Set();
    Object.values(_cpPropsMap).forEach(p => {
      if (p.structure_id !== sid) return;
      if (p.outbound_node) movingTips.add(p.outbound_node);
      if (p.inbound_node)  movingTips.add(p.inbound_node);
    });
    _moveState.connectors = [];
    Object.entries(_lineNodeMap).forEach(([lid, {s, e}]) => {
      if (_lineStructMap[lid]) return;           // skip internal lines
      const pl = _lineMap[lid];
      if (!pl) return;
      const lls = pl.getLatLngs();
      if (movingTips.has(s)) {
        _moveState.connectors.push({ lid, endIdx: 0, origLatlng: lls[0] });
      } else if (movingTips.has(e)) {
        _moveState.connectors.push({ lid, endIdx: lls.length - 1, origLatlng: lls[lls.length - 1] });
      }
    });

    // Hide all internal lines in one call — the structure layer group is
    // removed from _layers.lines here and rebuilt by App._render() on drop.
    const structLg = _structureLayerMap[sid];
    if (structLg) _layers.lines.removeLayer(structLg);

    _moveState.active      = true;
    _moveState.sid         = sid;
    _moveState.startLatlng = latlng;
    setStatus(`Moving ${sid} — release to drop`);
    return;
  }

  // ── Branch B: existing handle nearby → move it; else insert new bend ──
  const layerPt     = map.latLngToLayerPoint(latlng);
  const existHandle = _nearestWaypointHandle(latlng);

  if (existHandle) {
    // Move an existing waypoint handle (and its partner)
    const { lid, partnerId, idx } = existHandle._wptData;
    _bendState.active = true;
    _bendState.mode   = 'existing';
    _bendState.handle = existHandle;
    _bendState.exLid  = lid;
    _bendState.exPid  = partnerId;
    _bendState.exIdx  = idx;
    setStatus(`Moving waypoint ${idx} — release to set`);

  } else {
    // Insert a new bend point on all free guideways within the grab radius
    const nearLids = _freeGuideywaysNear(latlng);
    if (nearLids.length === 0) return;

    _bendState.origLls   = {};
    _bendState.segIdxMap = {};

    nearLids.forEach(lid => {
      const pl = _lineMap[lid];
      if (!pl) return;
      _bendState.origLls[lid] = [...pl.getLatLngs()];
      const pts = pl.getLatLngs().map(ll => map.latLngToLayerPoint(ll));
      let bestSeg = 0, bestD = Infinity;
      for (let i = 0; i < pts.length - 1; i++) {
        const cp = L.LineUtil.closestPointOnSegment(layerPt, pts[i], pts[i + 1]);
        const d  = layerPt.distanceTo(cp);
        if (d < bestD) { bestD = d; bestSeg = i; }
      }
      const lls = [...pl.getLatLngs()];
      lls.splice(bestSeg + 1, 0, latlng);
      pl.setLatLngs(lls);
      _bendState.segIdxMap[lid] = bestSeg + 1;
    });

    _bendState.active = true;
    _bendState.mode   = 'new';
    _bendState.tempMk = L.marker(latlng, {
      icon: L.divIcon({ className: "align-handle", iconSize: [14, 14], iconAnchor: [7, 7] }),
      zIndexOffset: 1000,
      interactive: false,
    }).addTo(_layers.waypoints);

    setStatus(`Bending ${nearLids.length} guideway(s) — release to set`);
  }
}, { capture: true });

// Document-level mousemove — live preview (structure move OR guideway bend).
document.addEventListener("mousemove", (e) => {
  const latlng = map.mouseEventToLatLng(e);

  if (_moveState.active) {
    // CP markers and connector guideway endpoints follow the drag live.
    // Internal lines were removed on drag start; they rebuild on drop via _render.
    const dlat = latlng.lat - _moveState.startLatlng.lat;
    const dlon = latlng.lng - _moveState.startLatlng.lng;
    Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
      if (props.structure_id !== _moveState.sid) return;
      const orig = _moveState.origPos[cpId];
      if (orig) _nodeMap[cpId]?.setLatLng([orig.lat + dlat, orig.lng + dlon]);
    });
    // Stretch/shrink connector lines so they remain attached to the moving structure
    _moveState.connectors.forEach(c => {
      const pl = _lineMap[c.lid];
      if (!pl) return;
      const lls = pl.getLatLngs();
      lls[c.endIdx] = L.latLng(c.origLatlng.lat + dlat, c.origLatlng.lng + dlon);
      pl.setLatLngs(lls);
    });
  }

  if (_bendState.active) {
    if (_bendState.mode === 'existing') {
      // Move the existing handle marker and both its polylines
      const { handle, exLid, exPid, exIdx } = _bendState;
      if (handle) handle.setLatLng(latlng);
      [exLid, exPid].filter(Boolean).forEach(id => {
        const pl = _lineMap[id];
        if (!pl) return;
        const lls = pl.getLatLngs();
        lls[exIdx + 1] = latlng;   // +1: index 0 is start_node
        pl.setLatLngs(lls);
      });
    } else {
      // Move the temp handle and all new-bend polylines
      if (_bendState.tempMk) _bendState.tempMk.setLatLng(latlng);
      Object.entries(_bendState.segIdxMap).forEach(([lid, segIdx]) => {
        const pl = _lineMap[lid];
        if (!pl) return;
        const lls = pl.getLatLngs();
        lls[segIdx] = latlng;
        pl.setLatLngs(lls);
      });
    }
  }
});

// Document-level mouseup — commit (structure move OR guideway bend).
document.addEventListener("mouseup", async (e) => {
  const latlng = map.mouseEventToLatLng(e);

  // ── Guideway bend commit ───────────────────────────────────────────────
  if (_bendState.active) {
    const mode = _bendState.mode;
    _bendState.active = false;
    _bendState.mode   = null;

    if (mode === 'existing') {
      const { exLid, exPid, exIdx } = _bendState;
      _bendState.handle = null;
      _bendState.exLid = _bendState.exPid = _bendState.exIdx = null;
      const updates = [api("PUT", `/api/network/line/${exLid}/waypoint/${exIdx}`,
                           { lat: latlng.lat, lon: latlng.lng })];
      if (exPid) updates.push(api("PUT", `/api/network/line/${exPid}/waypoint/${exIdx}`,
                                  { lat: latlng.lat, lon: latlng.lng }));
      await Promise.all(updates);
    } else {
      if (_bendState.tempMk) { map.removeLayer(_bendState.tempMk); _bendState.tempMk = null; }
      const lids = Object.keys(_bendState.segIdxMap);
      _bendState.segIdxMap = {};
      _bendState.origLls   = {};
      const results = await Promise.all(
        lids.map(lid => api("POST", `/api/network/line/${lid}/waypoint`,
                            { lat: latlng.lat, lon: latlng.lng }))
      );
      if (results.some(r => r.error)) { alert(results.find(r => r.error).error); }
    }

    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(mode === 'existing' ? "Waypoint moved" : "Bend set");
    return;
  }

  if (!_moveState.active) return;
  _moveState.active = false;
  _moveState.connectors = [];
  map.dragging.enable();   // re-enable in case waypoint handler disabled it

  const dlat   = latlng.lat - _moveState.startLatlng.lat;
  const dlon   = latlng.lng - _moveState.startLatlng.lng;
  const sid    = _moveState.sid;
  _moveState.sid = null;

  if (Math.abs(dlat) < 1e-9 && Math.abs(dlon) < 1e-9) {
    setStatus("Ready");
    return;
  }

  const r = await api("POST", `/api/network/structure/${sid}/move`, { dlat, dlon });
  if (r.error) { alert(r.error); }
  const geojson = await api("GET", "/api/network");
  App._render(geojson);
  setStatus(`Moved ${sid}`);
});

async function deleteSelection() {
  if (_sel.structures.size + _sel.freeNodes.size === 0) return;
  setStatus("Deleting…");

  for (const sid of _sel.structures) {
    await api("DELETE", `/api/network/structure/${sid}`);
  }
  for (const nid of _sel.freeNodes) {
    await api("DELETE", `/api/network/node/${nid}`);
  }

  _clearSelection();
  const geojson = await api("GET", "/api/network");
  App._render(geojson);
  setStatus("Selection deleted");
}

// ── App module ────────────────────────────────────────────────────────────────

const App = {

  async newNetwork() {
    if (!confirm("Start a new empty network?")) return;
    const r = await api("POST", "/api/network/new", { network_id: "untitled" });
    App._render(r);
    setStatus("New network");
  },

  openFile() {
    document.getElementById("file-input").click();
  },

  async onFileSelected(input) {
    const file = input.files[0];
    if (!file) return;
    // We need a server-side path; upload or read directly.
    // For desktop use: read file content and POST to server which saves to temp, then loads.
    const text = await file.text();
    const r = await _postRaw("/api/network/load_text", {
      filename: file.name,
      content: text,
    });
    if (r.error) { alert(r.error); return; }
    _fitOnNextRender = true;
    App._render(r);
    setStatus(`Loaded: ${file.name}`);
    input.value = "";
  },

  async saveFile() {
    // Fetch the .jpd content from the server as a blob
    let blob, filename;
    try {
      const resp = await fetch("/api/network/download");
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(err.error || "Save failed");
        return;
      }
      blob = await resp.blob();
      // Derive filename from Content-Disposition header, fallback to "network.jpd"
      const cd = resp.headers.get("Content-Disposition") || "";
      const m  = cd.match(/filename="?([^"]+)"?/);
      filename = m ? m[1] : "network.jpd";
    } catch (e) {
      alert("Save failed: " + e.message);
      return;
    }

    // Native OS save dialog via File System Access API (Chrome 86+, Safari 15.2+, Edge 86+)
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: [{ description: "JPods network file", accept: { "application/xml": [".jpd"] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        setStatus(`Saved: ${handle.name}`);
        return;
      } catch (e) {
        if (e.name === "AbortError") return;  // user cancelled — do nothing
        // Fall through to blob-download fallback on other errors
      }
    }

    // Fallback: trigger browser download (goes to Downloads or prompts, per browser prefs)
    const url = URL.createObjectURL(blob);
    const a   = document.createElement("a");
    a.href     = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    setStatus(`Saved: ${filename}`);
  },

  async captureMap() {
    setStatus("Capturing map…");
    try {
      const canvas = await html2canvas(document.getElementById("map"), {
        useCORS:    true,
        allowTaint: false,
        logging:    false,
        // Exclude the palette div (it floats over the map) — clone-based approach
        ignoreElements: el => el.id === "palette",
      });
      canvas.toBlob(async (blob) => {
        const dt       = new Date().toISOString().slice(0, 10);
        const filename = `jpods-network-${dt}.png`;
        if (window.showSaveFilePicker) {
          try {
            const handle = await window.showSaveFilePicker({
              suggestedName: filename,
              types: [{ description: "PNG image", accept: { "image/png": [".png"] } }],
            });
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
            setStatus(`Captured: ${handle.name}`);
            return;
          } catch (e) {
            if (e.name === "AbortError") { setStatus("Ready"); return; }
          }
        }
        // Fallback
        const url = URL.createObjectURL(blob);
        const a   = document.createElement("a");
        a.href     = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        setStatus(`Captured: ${filename}`);
      }, "image/png");
    } catch (e) {
      alert("Map capture failed: " + e.message);
      setStatus("Ready");
    }
  },

  _render(geojson) {
    if (!geojson || !geojson.features) return;

    // Clear existing
    _layers.lines.clearLayers();
    _layers.nodes.clearLayers();
    _layers.waypoints.clearLayers();
    Object.keys(_lineMap).forEach(k => delete _lineMap[k]);
    Object.keys(_nodeMap).forEach(k => delete _nodeMap[k]);
    Object.keys(_partnerMap).forEach(k => delete _partnerMap[k]);
    Object.keys(_cpPropsMap).forEach(k => delete _cpPropsMap[k]);
    Object.keys(_lineStructMap).forEach(k => delete _lineStructMap[k]);
    Object.keys(_structureMetaMap).forEach(k => delete _structureMetaMap[k]);
    Object.keys(_structureLayerMap).forEach(k => delete _structureLayerMap[k]);
    Object.keys(_lineNodeMap).forEach(k => delete _lineNodeMap[k]);
    _hoverStructSid = null;
    _hoverLineId    = null;
    _clearSelection();

    // Build structure meta + line→structure maps, and create one L.layerGroup
    // per structure.  All internal polylines are added to their structure's group
    // so the entire structure can be shown/hidden with a single removeLayer call.
    const _structs = (geojson.metadata || {}).structures || {};
    Object.assign(_structureMetaMap, _structs);
    Object.entries(_structs).forEach(([sid, meta]) => {
      (meta.line_ids || []).forEach(lid => { _lineStructMap[lid] = sid; });
      const lg = L.layerGroup();
      _structureLayerMap[sid] = lg;
      _layers.lines.addLayer(lg);
    });

    // Draw lines first (below nodes)
    geojson.features
      .filter(f => f.properties.type === "line")
      .forEach(f => _addLineFeature(f));

    // Draw free nodes (skip internal structure nodes)
    geojson.features
      .filter(f => ["station","switch"].includes(f.properties.type) &&
                   !f.properties.is_internal)
      .forEach(f => _addNodeFeature(f));

    // Draw CP stub-pair markers (one per connection point)
    geojson.features
      .filter(f => f.properties.type === "cp")
      .forEach(f => _addCpFeature(f));

    // Flag structures with no connected CPs so users can see orphans
    _markOrphans();

    // Draw waypoint markers for all lines that have them
    geojson.features
      .filter(f => f.properties.type === "line" &&
                   f.properties.via_markers && f.properties.via_markers.length)
      .forEach(f => _renderWaypointMarkers(f));

    // Update sidebar
    const m = geojson.metadata || {};
    document.getElementById("net-stats").innerHTML =
      `<b>${m.network_id || "—"}</b><br>
       Nodes: ${m.node_count || 0} &nbsp; Lines: ${m.line_count || 0}<br>
       Stations: ${m.station_count || 0} &nbsp; Total: ${m.total_km || 0} km`;
    document.getElementById("status-net").textContent =
      `${m.station_count || 0} stations · ${m.line_count || 0} lines · ${m.total_km || 0} km`;

    // Fit map only when explicitly loading a file (not on every edit)
    if (_fitOnNextRender) {
      _fitOnNextRender = false;
      const pts = geojson.features
        .filter(f => f.geometry.type === "Point")
        .map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
      if (pts.length > 1) {
        map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 18 });
      } else if (pts.length === 1) {
        map.setView(pts[0], 17);
      }
    }
  },

  getMap() { return map; },
  getLayers() { return _layers; },
  getLineMap() { return _lineMap; },
  getNodeMap() { return _nodeMap; },
  getPartnerLine(lid) { return _partnerMap[lid] || null; },
};

// ── Line rendering ────────────────────────────────────────────────────────────

function _addLineFeature(f) {
  const lid          = f.properties.line_id;
  const coords       = f.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
  const lineRole     = f.properties.line_role;
  const isConverging = f.properties.is_converging;

  // Track start/end node IDs so connector endpoints can follow structure moves
  _lineNodeMap[lid] = { s: f.properties.start_node, e: f.properties.end_node };

  // Color by role:
  //   connector (CP↔CP through-guideway) → green  (has both inbound + outbound ends)
  //   siding (internal station track)    → inverted red/blue
  //   all others                         → blue=outbound, red=inbound
  let color;
  if (lineRole === "connector") {
    color = "#27ae60";                                          // green
  } else if (lineRole === "siding") {
    color = isConverging ? "#3498db" : "#e74c3c";              // inverted
  } else {
    color = isConverging ? "#e74c3c" : "#3498db";              // normal
  }

  const pl = L.polyline(coords, {
    color,
    weight: 2.5,
    opacity: 0.85,
  });

  // Arrowhead (if plugin available)
  if (pl.arrowheads) {
    pl.arrowheads({ size: "8px", frequency: "endonly", fill: true });
  }

  const structSid = _lineStructMap[lid];  // set if this line belongs to a structure

  if (structSid) {
    // ── Internal structure line — object behavior ──────────────────────────
    // Cannot be broken, waypointed, or inspected individually.
    // Hover arms the Alt+drag handle; click selects the parent structure.
    pl.on("mouseover", () => { _hoverStructSid = structSid; });
    pl.on("mouseout",  () => { if (_hoverStructSid === structSid) _hoverStructSid = null; });
    pl.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      if (_moveState.active) return;
      _selectedStructSid = structSid;
      _selectedCpId      = null;
      _selectedNodeId    = null;
      setStatus(`${structSid} selected — Delete to remove · Alt+drag to move`);
    });
    pl.bindTooltip(structSid, { sticky: true, className: "line-tooltip" });

  } else {
    // ── Free guideway — individual behavior ───────────────────────────────
    // Track hover so Alt+mousedown knows which line to bend
    pl.on("mouseover", () => { _hoverLineId = lid; });
    pl.on("mouseout",  () => { if (_hoverLineId === lid) _hoverLineId = null; });

    pl.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      if (Editor.isWaypointing()) return;
      if (e.originalEvent.shiftKey) {
        Waypoints.addWaypoint(lid, e.latlng.lat, e.latlng.lng);
      } else if (e.originalEvent.ctrlKey || e.originalEvent.metaKey) {
        Editor.breakLine(lid);
      } else {
        _showLineInfo(f.properties);
      }
    });
    pl.on("contextmenu", (e) => {
      L.DomEvent.stopPropagation(e);
      L.DomEvent.preventDefault(e);
      if (Editor.isWaypointing()) {
        Waypoints.addAlignWaypoint(lid, e.latlng.lat, e.latlng.lng);
      }
    });
    pl.bindTooltip(
      `Line ${lid}<br>${f.properties.length_m} m`,
      { sticky: true, className: "line-tooltip" }
    );
  }

  // Route into structure layer group or free-guideway layer
  const structLg = _structureLayerMap[_lineStructMap[lid]];
  if (structLg) structLg.addLayer(pl);
  else          _layers.lines.addLayer(pl);

  _lineMap[lid] = pl;
  if (f.properties.partner_id) _partnerMap[lid] = f.properties.partner_id;
}

// ── Node rendering ────────────────────────────────────────────────────────────

function _nodeIcon(type, nodeRole) {
  if (nodeRole === "cp_tip") {
    return L.divIcon({ className: "node-marker-cp", iconSize: null });
  }
  const cls = {
    station: "node-marker-station",
    switch:  "node-marker-switch",
  }[type] || "node-marker-switch";
  return L.divIcon({ className: cls, iconSize: null });
}

function _addNodeFeature(f) {
  const [lng, lat] = f.geometry.coordinates;
  const type = f.properties.type;
  const nid  = f.properties.node_id;

  const nodeRole = f.properties.node_role;
  const marker = L.marker([lat, lng], {
    icon: _nodeIcon(type, nodeRole),
    draggable: false,
  });

  marker.bindTooltip(nid, { direction: "top", offset: [0, -6] });

  marker.on("click", (e) => {
    if (e.originalEvent.shiftKey) {
      Editor.removeNode(nid);
    } else if (Editor.isDrawingLine()) {
      Editor.lineNodeClick(nid, lat, lng);
    } else {
      // Select this node — Delete key will remove it
      _selectedNodeId = nid;
      setStatus(`${nid} selected — press Delete to remove`);
      if (type === "station") _showStationPanel(nid);
    }
  });

  _layers.nodes.addLayer(marker);
  _nodeMap[nid] = marker;
}

// ── CP stub-pair markers ──────────────────────────────────────────────────────

let _selectedCpId    = null;   // cp_id of first CP clicked, waiting for a partner
let _selectedNodeId  = null;   // node_id of last-clicked node (Delete key removes it)
let _selectedStructSid = null; // structure_id of last-clicked structure (Delete key removes it)

function _cpIcon(props, selected, isOrphan = false) {
  const isCircle  = props.structure_type === "traffic_circle";
  const connected = !!props.connected_to;
  const heading   = props.heading_deg || 0;

  const markerCls = [
    "cp-marker",
    isCircle  ? "cp-circle"    : "",
    connected ? "cp-connected" : "",
    isOrphan  ? "cp-orphan"    : "",
  ].filter(Boolean).join(" ");
  const hitCls = ["cp-hit", selected ? "cp-hit-selected" : ""].filter(Boolean).join(" ");

  // Rotate the badge so the right-side dot always sits over the outbound stub
  // and the left-side dot over the inbound stub, regardless of heading.
  // Logic: CSS rotate(heading°) CW maps the badge's right edge to bearing
  // (90 + heading)° = east_h = the outbound (right-of-travel) direction.
  // Dot order: cp-in first (left), cp-out second (right).
  return L.divIcon({
    className: "",
    html: `<div class="${hitCls}">
             <div class="${markerCls}" style="transform:rotate(${heading}deg)">
               <div class="cp-dot cp-in"></div>
               <div class="cp-dot cp-out"></div>
             </div>
           </div>`,
    iconSize:   [100, 50],
    iconAnchor: [ 50, 25],
  });
}

// Detect orphaned structures (all CPs unconnected) and pulse their markers.
// Called at end of every _render so it reflects the current network state.
function _markOrphans() {
  // Group CP ids by structure
  const structCps = {};
  Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
    (structCps[props.structure_id] = structCps[props.structure_id] || []).push(cpId);
  });

  // A structure is an orphan if every one of its CPs has connected_to === null
  const orphanSids = new Set(
    Object.entries(structCps)
      .filter(([, cpIds]) => cpIds.every(id => !_cpPropsMap[id].connected_to))
      .map(([sid]) => sid)
  );

  // Update marker icons for all CPs
  Object.entries(_cpPropsMap).forEach(([cpId, props]) => {
    const mk = _nodeMap[cpId];
    if (!mk) return;
    const isOrphan   = orphanSids.has(props.structure_id);
    const isSelected = cpId === _selectedCpId;
    mk.setIcon(_cpIcon(props, isSelected, isOrphan));
    const tip = isOrphan
      ? `${cpId} ⚠ no connections — click to connect`
      : props.connected_to
        ? `${cpId} ↔ ${props.connected_to}  (Shift+click to disconnect)`
        : `${cpId} (open — click to select)`;
    mk.setTooltipContent(tip);
  });

  return orphanSids.size;
}

function _addCpFeature(f) {
  const [lng, lat] = f.geometry.coordinates;
  const props      = f.properties;
  const cpId       = props.cp_id;
  const connected  = !!props.connected_to;
  const isSelected = cpId === _selectedCpId;

  const marker = L.marker([lat, lng], {
    icon: _cpIcon(props, isSelected),
    draggable: false,
  });

  marker.bindTooltip(
    connected
      ? `${cpId} ↔ ${props.connected_to}  (Shift+click to disconnect)`
      : `${cpId} (open — click to select)`,
    { direction: "top", offset: [0, -30] }
  );

  // Track hover so the document capture mousedown knows which structure to move
  marker.on("mouseover", () => { _hoverStructSid = props.structure_id; });
  marker.on("mouseout",  () => { if (_hoverStructSid === props.structure_id) _hoverStructSid = null; });

  marker.on("click", async (e) => {
    L.DomEvent.stopPropagation(e);  // prevent click reaching map (avoids accidental placement)

    // In line-draw mode, CP click feeds the node into the guideway draw tool.
    // In all other modes (including placement modes), fall through to CP connect/disconnect.
    // stopPropagation above already prevents the placement handler from also firing.
    const mode = Editor.getMode();

    // Shift+click on a connected CP → disconnect
    if (e.originalEvent.shiftKey && connected) {
      _selectedCpId = null;
      const r = await api("POST", "/api/network/disconnect_cp", { cp_id: cpId });
      if (r.error) { alert(r.error); return; }
      const gj = await api("GET", "/api/network");
      App._render(gj);
      setStatus(`Disconnected ${cpId}`);
      return;
    }

    if (Editor.isDrawingLine()) {
      Editor.lineNodeClick(props.outbound_node, lat, lng);
      return;
    }

    if (_selectedCpId === null) {
      // First click — select this CP and show its structure's rotation panel
      _selectedCpId = cpId;
      marker.setIcon(_cpIcon(props, true));
      setStatus(`${cpId} selected — click another CP to connect  ·  Shift+click to disconnect  (Esc to cancel)`);
      // Show rotation panel for the parent structure
      const meta = (await api("GET", "/api/network")).metadata || {};
      const structs = meta.structures || {};
      const s = structs[props.structure_id];
      if (s) StructPanel.show(s.structure_id, s.structure_type, s.heading_deg, s.arm_headings);

    } else if (_selectedCpId === cpId) {
      // Click same CP again — deselect
      _selectedCpId = null;
      marker.setIcon(_cpIcon(props, false));
      setStatus("Ready");

    } else {
      // Second click — connect the two CPs
      const partnerCpId = _selectedCpId;
      _selectedCpId = null;
      const r = await api("POST", "/api/network/connect_cps",
                          { cp_a: partnerCpId, cp_b: cpId });
      if (r.error) { alert(r.error); return; }
      const gj = await api("GET", "/api/network");
      App._render(gj);
      setStatus(`Connected ${partnerCpId} ↔ ${cpId}  (${r.lines_added.length} guideways added)`);
    }
  });

  _layers.nodes.addLayer(marker);
  _nodeMap[cpId] = marker;
  _cpPropsMap[cpId] = props;
}

// ── Waypoint markers ─────────────────────────────────────────────────────────

function _renderWaypointMarkers(lineFeature) {
  const lid       = lineFeature.properties.line_id;
  const partnerId = lineFeature.properties.partner_id || null;
  const vias      = lineFeature.properties.via_markers || [];
  const pl        = _lineMap[lid];

  // Only render one set of handles per paired guideway — the lexicographically
  // "lower" line ID owns the handles; the partner's handles are skipped since
  // both lines' waypoints move together when dragged.
  if (partnerId && lid > partnerId) return;

  vias.forEach(({ lat, lon, idx }) => {
    const partnerPl = partnerId ? _lineMap[partnerId] : null;

    const dmk = L.marker([lat, lon], {
      icon: L.divIcon({
        className:  "align-handle",
        iconSize:   [14, 14],
        iconAnchor: [7, 7],
      }),
      draggable: true,
      title: `Align waypoint ${idx}\nDrag to move both guideways\nShift-click to remove`,
    });
    // Tag with metadata so Alt+grab can detect and move existing handles
    dmk._wptData = { lid, partnerId, idx };

    dmk.on("drag", (e) => {
      // Move both guideways in real time
      if (pl) {
        const latlngs = pl.getLatLngs();
        latlngs[idx + 1] = e.latlng;  // +1: index 0 is start_node
        pl.setLatLngs(latlngs);
      }
      if (partnerPl) {
        const latlngs = partnerPl.getLatLngs();
        latlngs[idx + 1] = e.latlng;
        partnerPl.setLatLngs(latlngs);
      }
    });

    dmk.on("dragend", async (e) => {
      const { lat: nlat, lng: nlon } = e.target.getLatLng();
      const updates = [
        api("PUT", `/api/network/line/${lid}/waypoint/${idx}`, { lat: nlat, lon: nlon }),
      ];
      if (partnerId) {
        updates.push(api("PUT", `/api/network/line/${partnerId}/waypoint/${idx}`,
                         { lat: nlat, lon: nlon }));
      }
      await Promise.all(updates);
      const geojson = await api("GET", "/api/network");
      App._render(geojson);
    });

    // Stop mousedown from bubbling to the map's _wpt drag system
    dmk.on("mousedown", (e) => { L.DomEvent.stopPropagation(e); });

    dmk.on("click", (e) => {
      if (e.originalEvent.shiftKey) {
        Waypoints.removeAlignWaypoint(lid, partnerId, idx);
      }
    });

    _layers.waypoints.addLayer(dmk);
  });
}

// ── Info panels ───────────────────────────────────────────────────────────────

function _showLineInfo(props) {
  setStatus(`Line ${props.line_id}: ${props.start_node} → ${props.end_node} (${props.length_m} m)`);
}

function _showStationPanel(nid) {
  document.getElementById("panel-station").style.display = "";
  document.getElementById("station-id").textContent = nid;
  document.getElementById("station-detail").textContent = "Click 'Run Sim' for demand data.";
}

// ── Structure panel (rotation) ────────────────────────────────────────────────

const StructPanel = (() => {
  let _sid = null;
  let _type = null;
  let _currentHeading = 0;
  let _currentArms = [];

  const STATION_PRESETS  = [{label:"N–S",h:0},{label:"E–W",h:90},{label:"NE–SW",h:45},{label:"NW–SE",h:135}];
  const CIRCLE_ROTATIONS = [{label:"N/E/S/W",delta:0},{label:"+45°",delta:45},{label:"+90°",delta:90},{label:"+135°",delta:135}];

  function show(structureId, structureType, headingDeg, armHeadings) {
    _sid  = structureId;
    _type = structureType;
    _currentHeading = headingDeg || 0;
    _currentArms    = armHeadings || [];

    document.getElementById("struct-id").textContent   = structureId;
    document.getElementById("struct-type").textContent = structureType === "station" ? "Station" : "Traffic Circle";
    document.getElementById("struct-heading-input").value = Math.round(_currentHeading);

    // Build preset buttons
    const btns = document.getElementById("struct-heading-btns");
    btns.innerHTML = "";
    const presets = structureType === "station" ? STATION_PRESETS : CIRCLE_ROTATIONS;
    presets.forEach(p => {
      const b = document.createElement("button");
      b.textContent = p.label;
      b.style.cssText = "background:#3a3a3a;border:1px solid #555;color:#ddd;border-radius:3px;padding:4px 2px;font-size:10px;cursor:pointer;text-align:center";
      b.onclick = () => {
        if (_type === "station") {
          _rotate({ heading_deg: p.h });
        } else {
          _rotate({ rotation_deg: p.delta });
        }
      };
      btns.appendChild(b);
    });

    document.getElementById("panel-structure").style.display = "";
  }

  async function _rotate(body) {
    if (!_sid) return;
    const r = await api("POST", `/api/network/structure/${_sid}/rotate`, body);
    if (r.error) { alert(r.error); return; }
    _currentHeading = r.heading_deg || 0;
    _currentArms    = r.arm_headings || [];
    document.getElementById("struct-heading-input").value = Math.round(_currentHeading);
    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(`${_sid} rotated`);
  }

  return {
    show,
    applyHeading() {
      const val = parseFloat(document.getElementById("struct-heading-input").value) || 0;
      if (_type === "station") {
        _rotate({ heading_deg: val });
      } else {
        _rotate({ arm_headings: _currentArms.map(h => (h + val) % 360) });
      }
    },
    hide() {
      document.getElementById("panel-structure").style.display = "none";
      _sid = null;
    },
  };
})();

// ── Status helpers ────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status-mode").textContent = msg;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

async function _postRaw(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

// ── Waypoint tool — hover circle + click-drag-release ────────────────────────
//
// When the Waypoint tool is active:
//   • Hover near a guideway → teal capture circle snaps to the line
//   • Mousedown (left) → disable map pan, start drag, preview both polylines live
//   • Mouseup → POST waypoint to both guideways at release position, re-render
//   • Right-click a line → place waypoint on both (handled in line contextmenu above)
//   • Escape mid-drag → restore original polylines, cancel

const _wpt = {
  circle:     null,   // L.circleMarker — hover indicator
  nearLid:    null,   // line id nearest to cursor (when hovering)
  dragging:   false,
  dragLid:    null,
  dragPid:    null,   // partner line id
  dragSegIdx: 0,      // which segment to insert into
  origLls:    {},     // snapshot { lid: [...LatLng] } taken at mousedown
  tempMk:     null,   // draggable temp handle marker
};

// Use layer coordinates (correct for closestLayerPoint)
function _wptNearest(latlng) {
  const layerPt = map.latLngToLayerPoint(latlng);
  let bestLid = null, bestDist = Infinity, bestSnap = null;
  Object.entries(_lineMap).forEach(([lid, pl]) => {
    const cp = pl.closestLayerPoint(layerPt);
    if (cp && cp.distance < bestDist) {
      bestDist = cp.distance;
      bestLid  = lid;
      bestSnap = map.layerPointToLatLng(cp);
    }
  });
  return (bestLid && bestDist <= 30) ? { lid: bestLid, snap: bestSnap } : null;
}

// Find which segment of pl is closest to layerPt (returns index i → insert after pts[i])
function _wptSegment(pl, layerPt) {
  const pts = pl.getLatLngs().map(ll => map.latLngToLayerPoint(ll));
  let best = 0, bestD = Infinity;
  for (let i = 0; i < pts.length - 1; i++) {
    const cp = L.LineUtil.closestPointOnSegment(layerPt, pts[i], pts[i + 1]);
    const d  = layerPt.distanceTo(cp);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

function _wptHideCircle() {
  if (_wpt.circle && map.hasLayer(_wpt.circle)) map.removeLayer(_wpt.circle);
}

// Called by editor.js Escape handler to abort a drag in progress
function wptCancel() {
  if (!_wpt.dragging) return;
  _wpt.dragging = false;
  map.dragging.enable();
  if (_wpt.tempMk) { map.removeLayer(_wpt.tempMk); _wpt.tempMk = null; }
  // Restore original polylines
  Object.entries(_wpt.origLls).forEach(([lid, orig]) => {
    const pl = _lineMap[lid];
    if (pl) pl.setLatLngs(orig);
  });
  _wpt.origLls = {};
  if (_wpt.circle) _wpt.circle.setStyle({ fillOpacity: 0.25, weight: 3 });
}

map.on("mousemove", (e) => {
  if (!Editor.isWaypointing()) { _wptHideCircle(); return; }
  if (_moveState.active) return;   // structure move in progress — skip waypoint preview

  if (_wpt.dragging) {
    // Live drag: update temp handle + both polylines
    if (_wpt.tempMk) _wpt.tempMk.setLatLng(e.latlng);
    const si = _wpt.dragSegIdx;
    Object.entries(_wpt.origLls).forEach(([lid, orig]) => {
      const pl = _lineMap[lid];
      if (pl) pl.setLatLngs([...orig.slice(0, si + 1), e.latlng, ...orig.slice(si + 1)]);
    });
    return;
  }

  // Hover: show/update capture circle
  const hit = _wptNearest(e.latlng);
  if (!hit) { _wptHideCircle(); _wpt.nearLid = null; return; }

  _wpt.nearLid = hit.lid;
  if (!_wpt.circle) {
    _wpt.circle = L.circleMarker(hit.snap, {
      radius: 12, color: "#1abc9c", fillColor: "#1abc9c",
      fillOpacity: 0.25, weight: 3, interactive: false,
    }).addTo(map);
  } else {
    if (!map.hasLayer(_wpt.circle)) _wpt.circle.addTo(map);
    _wpt.circle.setLatLng(hit.snap);
  }
});

map.on("mousedown", (e) => {
  if (!Editor.isWaypointing()) return;
  if (e.originalEvent.button !== 0) return;   // left button only
  // Don't intercept clicks on existing waypoint handles
  if (e.originalEvent.target?.closest?.(".align-handle")) return;

  // Fresh nearest check at mousedown — don't trust stale hover state
  const hit = _wptNearest(e.latlng);
  if (!hit) return;

  e.originalEvent.preventDefault();
  map.dragging.disable();

  const lid = hit.lid;
  const pl  = _lineMap[lid];
  if (!pl) return;

  // If the clicked line belongs to a structure, move the whole structure.
  // (Waypoint routing inside a structure footprint is not useful — structures
  //  have fixed internal geometry that should move as a unit.)
  const structSid = _lineStructMap[lid];
  if (structSid) {
    _moveState.origPos = {};
    Object.entries(_cpPropsMap).forEach(([cpId, p]) => {
      if (p.structure_id !== structSid) return;
      const mk = _nodeMap[cpId];
      if (mk) _moveState.origPos[cpId] = mk.getLatLng();
    });
    // Hide all internal lines in one call via the structure layer group
    const wptStructLg = _structureLayerMap[structSid];
    if (wptStructLg) _layers.lines.removeLayer(wptStructLg);
    _moveState.active      = true;
    _moveState.sid         = structSid;
    _moveState.startLatlng = e.latlng;
    setStatus(`Moving ${structSid} — release to drop`);
    return;
  }

  // Partner lookup: check both forward and reverse in _partnerMap
  // (hover may have snapped to either of the two parallel guideways)
  const pid = _partnerMap[lid] ||
              Object.keys(_partnerMap).find(k => _partnerMap[k] === lid) ||
              null;

  _wpt.dragging   = true;
  _wpt.dragLid    = lid;
  _wpt.dragPid    = pid;
  _wpt.dragSegIdx = _wptSegment(pl, map.latLngToLayerPoint(e.latlng));

  // Temp handle at click position
  _wpt.tempMk = L.marker(e.latlng, {
    icon: L.divIcon({ className: "align-handle", iconSize: [14, 14], iconAnchor: [7, 7] }),
    zIndexOffset: 1000,
    interactive: false,
  }).addTo(_layers.waypoints);

  if (_wpt.circle) _wpt.circle.setStyle({ fillOpacity: 0.6, weight: 4 });
});

async function _wptCommit(latlng) {
  if (!_wpt.dragging) return;
  _wpt.dragging = false;
  map.dragging.enable();
  if (_wpt.tempMk) { map.removeLayer(_wpt.tempMk); _wpt.tempMk = null; }
  if (_wpt.circle) _wpt.circle.setStyle({ fillOpacity: 0.25, weight: 3 });
  if (_wpt.dragLid) {
    await Waypoints.addAlignWaypoint(_wpt.dragLid, latlng.lat, latlng.lng);
  }
}

map.on("mouseup", (e) => _wptCommit(e.latlng));

// Safety net: release outside the map container
document.addEventListener("mouseup", (e) => {
  if (!_wpt.dragging) return;
  const r   = map.getContainer().getBoundingClientRect();
  const lpt = map.containerPointToLatLng(L.point(e.clientX - r.left, e.clientY - r.top));
  _wptCommit(lpt);
});

// ── Waypoints module ──────────────────────────────────────────────────────────

const Waypoints = {

  // Shift-click on a single line — adds to that line only
  async addWaypoint(lineId, lat, lon) {
    const r = await api("POST", `/api/network/line/${lineId}/waypoint`,
                        { lat, lon });
    if (r.error) { alert(r.error); return; }
    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(`Waypoint added to ${lineId}`);
  },

  // Align tool — adds to both guideways of the pair simultaneously
  async addAlignWaypoint(lineId, lat, lon) {
    // Check both directions: this line → partner, or partner → this line
    const partnerId = App.getPartnerLine(lineId) ||
                      Object.keys(_partnerMap).find(k => _partnerMap[k] === lineId) ||
                      null;
    const posts = [
      api("POST", `/api/network/line/${lineId}/waypoint`, { lat, lon }),
    ];
    if (partnerId) {
      posts.push(api("POST", `/api/network/line/${partnerId}/waypoint`, { lat, lon }));
    }
    const results = await Promise.all(posts);
    if (results.some(r => r.error)) { alert(results.find(r => r.error).error); return; }
    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(`Waypoint placed — drag to move both guideways`);
  },

  async removeWaypoint(lineId, idx) {
    const r = await api("DELETE", `/api/network/line/${lineId}/waypoint/${idx}`);
    if (r.error) { alert(r.error); return; }
    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(`Waypoint removed from ${lineId}`);
  },

  // Remove paired waypoints (from align handle)
  async removeAlignWaypoint(lineId, partnerId, idx) {
    const deletes = [
      api("DELETE", `/api/network/line/${lineId}/waypoint/${idx}`),
    ];
    if (partnerId) {
      deletes.push(api("DELETE", `/api/network/line/${partnerId}/waypoint/${idx}`));
    }
    await Promise.all(deletes);
    const geojson = await api("GET", "/api/network");
    App._render(geojson);
    setStatus(`Waypoint removed`);
  },

};

// ── Floating palette ──────────────────────────────────────────────────────────

const Palette = (() => {
  const el     = document.getElementById("palette");
  const header = document.getElementById("palette-header");
  const body   = document.getElementById("palette-body");
  const colBtn = document.getElementById("palette-collapse");

  // Restore saved position
  const saved = (() => {
    try { return JSON.parse(localStorage.getItem("rt_palette")); } catch { return null; }
  })();
  if (saved) {
    el.style.left = saved.left;
    el.style.top  = saved.top;
  }
  if (saved?.collapsed) {
    body.classList.add("collapsed");
    colBtn.textContent = "+";
  }

  // Drag
  let _drag = null;
  header.addEventListener("mousedown", e => {
    if (e.target === colBtn) return;
    const r = el.getBoundingClientRect();
    _drag = { ox: e.clientX - r.left, oy: e.clientY - r.top };
    e.preventDefault();
  });
  document.addEventListener("mousemove", e => {
    if (!_drag) return;
    el.style.left = Math.max(0, e.clientX - _drag.ox) + "px";
    el.style.top  = Math.max(0, e.clientY - _drag.oy) + "px";
  });
  document.addEventListener("mouseup", () => {
    if (_drag) _save();
    _drag = null;
  });

  function _save() {
    localStorage.setItem("rt_palette", JSON.stringify({
      left:      el.style.left,
      top:       el.style.top,
      collapsed: body.classList.contains("collapsed"),
    }));
  }

  return {
    toggle() {
      const collapsed = body.classList.toggle("collapsed");
      colBtn.textContent = collapsed ? "+" : "−";
      _save();
    },
  };
})();

// ── Bootstrap ─────────────────────────────────────────────────────────────────

(async () => {
  const geojson = await api("GET", "/api/network");
  App._render(geojson);
})();
