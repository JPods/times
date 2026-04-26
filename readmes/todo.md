# Route-Time — To-Do

## Save Selection as Template

**Status:** not started  
**Reference models:** `/Applications/RouteTime_JPods/templates/*.tld`

When a region is selected (Shift+drag), add a **"Save as Template"** button in the
status bar or palette that exports the selected structures and their connector lines
into the `.tld` XML format used by the legacy RouteTime app.

### .tld format (from existing templates)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<network id="<name>" ver="<unix-ms>">
  <Switches lastID="N">
    <Switch ID="SWn" lat="..." lon="..." />
    ...
  </Switches>
  <stations lastID="N">
    <Station ID="STn" lat="..." lon="..." />
  </stations>
  <Lines lastID="N">
    <line ID="Ln" startNodeId="..." endNodeId="...">
      <Coordinate lat="..." lon="..." />
      <Coordinate lat="..." lon="..." />
    </line>
    ...
  </Lines>
  <Groups lastID="N">
    <StationGroup ID="NGn" c="SWdiv" d="SWmerge" st="STn" type="sg" />
    <Circle ID="NGn" C1="..." C2="..." C3="..." D1="..." D2="..." D3="..." D4="..." type="cg" />
    <tmpl ID="NGn" idList="SW1,SW2,...,STn," type="template" />
  </Groups>
</network>
```

### Implementation notes

- Export coordinates **relative to the bounding-box centre** of the selection so
  the template can be placed anywhere (like the legacy app does).
- Map Route-Time structures to legacy IDs:
  - Station internal nodes → `<Switch>` (platform node → `<Station>`)
  - Traffic-circle nodes → `<Switch>` with `tcId` attribute
  - Station → `<StationGroup>` in `<Groups>`
  - Traffic circle → `<Circle>` in `<Groups>`
  - Selection as a whole → `<tmpl>` entry
- Add `POST /api/network/selection/export_template` endpoint that returns the XML.
- Add **Save Template** button to the palette (visible only when a selection exists).
- Saved files go to the user-configurable templates directory; default suggestion:
  same folder as the currently open `.jpd` file.

---

## Auto-Connect — UX Polish

**Status:** working but needs polish before it's teachable

Auto-Connect is a powerful tool — it connects all interior CPs using a greedy
nearest-neighbour algorithm, leaving boundary CPs open for the user to route
manually. But it's invisible and one-shot: there's no preview, no undo, and no
explanation of which CPs were connected vs skipped.

### What needs to happen before it's user-facing

- **Preview mode** — show proposed connections as dashed lines before committing;
  user confirms or cancels
- **Highlight skipped CPs** — after auto-connect, briefly highlight the CPs that
  were left open (boundary gates) so the user knows where to route next
- **Undo** — auto-connect should be undoable as a single action (see Undo item below)
- **Guided intro** — a short tooltip or first-run hint explaining the boundary rule:
  "Interior CPs are connected automatically. Outer boundary CPs are left for you
  to connect to adjacent network segments."
- **Incremental** — re-running auto-connect after adding new structures should only
  connect the new unconnected CPs, not re-process already-connected ones

---

## Other Backlog

- Siding placement tool (currently disabled in palette)
- Undo / redo (Ctrl+Z / Ctrl+Y)
- Multi-network composite view (overlay two `.jpd` files for comparison)
