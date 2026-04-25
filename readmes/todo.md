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

## Other backlog

- Siding placement tool (currently disabled in palette)
- Undo / redo (Ctrl+Z / Ctrl+Y)
- Multi-network composite view (overlay two `.jpd` files for comparison)
