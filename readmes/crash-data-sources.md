# All-Severity Crash Data Sources by State

**Purpose:** Noelle's primary station placement signal. Fatal-only data (FARS) is too sparse
for small cities. All-severity data shows shopping center intersections, school zones,
dangerous curves — the paths tracked into the grass.

**Storage:** `/Volumes/Allie/data/overlays/crashes_all_{st}.geojson`
**Refresh:** Annual — most states update quarterly or annually

---

## Harvestable Now (ArcGIS API — free, no registration)

These use the standard ArcGIS REST pattern:
```
{FeatureServer}/0/query?where=1=1&outFields=*&f=geojson&resultOffset=0&resultRecordCount=2000
```
Paginate with `resultOffset` in increments of 2000.

| State | Dataset | URL | Scope | Years |
|-------|---------|-----|-------|-------|
| OK | OKC Vision Zero | `https://services5.arcgis.com/2mOVdIcRtNH2JsSF/arcgis/rest/services/OKC_Crash_Map_WFL1/FeatureServer` | OKC only, all severity | 2018-2022 |
| OK | Top 25 Crash Intersections | `https://services6.arcgis.com/RBtoEUQ2lmN0K3GY/arcgis/rest/services/Intersections_2024_Top_25/FeatureServer` | Statewide, aggregated | 2024 |
| NC | Non-Motorist Crashes | `https://ncdot.maps.arcgis.com/home/item.html?id=d00e97d23146472cb5da78fc3dbc0274` | Statewide, ped+bike | 2007-2024 |
| NC | HSIP Intersections | `https://services.arcgis.com/NuWFvHYDMVmmxMeF/arcgis/rest/services/HSIP_INT_2022/FeatureServer` | Statewide, severity index | 2022 |
| MN | VRU Crashes | `https://services.arcgis.com/qWbGMYB49y8mLbRt/arcgis/rest/services/VRU_Crashes_2016_to_2021_2_view/FeatureServer` | Statewide, VRU only | 2016-2021 |
| SC | Spartanburg County | `https://services6.arcgis.com/bom7L4u7y1k0qkF1/arcgis/rest/services/Spartanburg_County_Crash_Data_Monthly_Update/FeatureServer` | County only | 2024+ |

## Requires Data Request (free, but manual process)

| State | System | Contact | Format | Notes |
|-------|--------|---------|--------|-------|
| TX | CRIS (Crash Records Info System) | `https://cris.dot.state.tx.us/public/Query/app/home` — submit Crash Data Request Form | CSV with lat/lon | Best statewide dataset. 10+ years. All severity. Free. |
| NC | TEAAS (all motor-vehicle) | `dlcarter4@ncdot.gov` or `https://connect.ncdot.gov/resources/safety/Pages/default.aspx` | Proprietary, exportable | Free for gov agencies, request form for others |
| MN | MNCrash (all-severity) | `https://mncrash.state.mn.us` — requires gov account; bulk via `dps.mn.gov/divisions/ots` | Web query | Full statewide, but access restricted |
| OK | OHSO (statewide all-crash) | Contact OHSO directly; TR-310 crash reports | Unknown | Custodian of all OK crash data |
| SC | SCCATTS | SCDPS OHSJP at (803) 896-9950 | Unknown | No public portal; request-based |
| NJ | NJDOT raw crash files | Contact NJDOT Safety Data unit | CSV | data.nj.gov has county-aggregated only (`https://data.nj.gov/Transportation/Total-NJ-Injury-Crash-Records-By-Year/epj9-teyh`) |

## National Fallback

| Source | Coverage | URL | Notes |
|--------|----------|-----|-------|
| NHTSA FARS | Fatal only, all states | `https://static.nhtsa.gov/nhtsa/downloads/FARS/{YEAR}/National/` | Bulk CSV, free. Currently used. |
| NHTSA CRSS | All-severity sample (not census) | `https://www.nhtsa.gov/crash-data-systems/crash-report-sampling-system` | Not georeferenced. National estimates only. |

---

## Harvesting Strategy

1. **Immediate:** Harvest the ArcGIS datasets above — OKC, NC non-motorist, NC HSIP, MN VRU
2. **Next:** Submit data request forms for TX CRIS and NC TEAAS
3. **Later:** Contact OHSO (OK statewide), SCDPS (SC), MNCrash (MN), NJDOT (NJ)
4. **Ongoing:** As each state's data arrives, add to `harvest_crashes.py` and store on 5TB

## How This Was Researched (2026-07-09)

Searched each state's DOT website, ArcGIS Hub, data.gov portals, and NHTSA references.
Most states do NOT publish all-severity crash data as bulk download. The pattern:
- Fatal data: national via FARS (easy)
- All-severity: state-by-state, each different (hard)
- ArcGIS Feature Services are the best automated source where they exist
- Many states require formal data request forms — free but manual
- Some require government/law-enforcement accounts (MN MNCrash)

The mess is real. This readme is the map through it.
