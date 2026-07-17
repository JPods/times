# MeshMobility Pre-Release Todo
**Created:** 2026-07-17
**Source:** Session review after Draw tool, auth, crossing detection, code cleanup work

## Mission Essential (before public demo)
- [ ] Test Cloudflare email gate end-to-end on meshmobility.com
- [ ] Verify WC3 contact creation works from MeshMobility auth flow

## Draw Tool
- [ ] Buffer parameter: extend City Mesh N miles beyond city fence (Boston + 5mi use case)
- [ ] Undo (Cmd+Z) for drawn lines — no undo at all right now
- [ ] Show line distances as you draw (total miles per corridor)

## Library
- [ ] My Networks tab (endpoint exists at /api/auth/my_networks, no UI yet)
- [ ] Noelle quality score on saved networks before library submission
- [ ] Thumbnail/preview image for library entries

## City Mesh
- [ ] Remember last city across sessions (localStorage)
- [ ] Multi-city: generate mesh for 2-3 adjacent cities, auto-connect at boundaries
- [ ] Exclude water bodies (rivers, lakes) from grid placement

## Auth
- [ ] Profile edit — user can update their info after initial form
- [ ] Delete account button (privacy commitment)
- [ ] Session indicator — show how long until CF token expires

## Landing Page
- [ ] Live counter: networks designed, cities covered (from Document records)
- [ ] Example screenshots or animated demo GIF
- [ ] Mobile-responsive test (landing looks fine, app probably doesn't)

## Data
- [ ] Server-side dedup of drawn lines (double-click duplicate fix is client-only)
- [ ] Network diff — compare two saved versions of the same city
- [ ] Export to KML/GeoJSON for city planners who use GIS tools

## Performance
- [ ] Lazy-load overlays (crash/AADT data is heavy on slow connections)
- [ ] Cap City Mesh at a warning, not silent truncation to 100 circles
