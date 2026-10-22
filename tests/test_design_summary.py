"""
Design summary — station/circle counts, route vs track miles, column count.
Run with:  python -m pytest mesh_mobility/tests/test_design_summary.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mesh_mobility.engine import Network
from mesh_mobility.engine.network import vincenty_m
from mesh_mobility.engine.structures import (
    build_station, build_traffic_circle, connect_cps, design_summary,
)


def _station_and_circle():
    """One station 1 km south of one traffic circle, joined by one CP pair."""
    net = Network("summary_test")
    cps = {}
    st, st_cps = build_station(net, 36.000, -95.900)
    tc, tc_cps = build_traffic_circle(net, 36.009, -95.900)
    cps.update(st_cps)
    cps.update(tc_cps)
    a = max(st_cps.values(), key=lambda c: c.center_lat)   # station's north CP
    b = min(tc_cps.values(), key=lambda c: c.center_lat)   # circle's south arm
    connect_cps(net, a, b, cps)
    net.build()
    return net, {st.structure_id: st, tc.structure_id: tc}, a, b


def test_counts_both_structure_types():
    net, structures, _, _ = _station_and_circle()
    s = design_summary(net, structures)
    assert s["station_count"] == 1
    assert s["circle_count"] == 1


def test_route_is_cp_gap_once_not_twice():
    net, structures, a, b = _station_and_circle()
    s = design_summary(net, structures)
    gap_mi = vincenty_m(a.center_lat, a.center_lon,
                        b.center_lat, b.center_lon) / 1609.34
    assert abs(s["route_miles"] - gap_mi) < 0.1
    assert s["track_miles"] > 2 * s["route_miles"]   # both directions + internals


def test_columns_one_per_span():
    net, structures, a, b = _station_and_circle()
    s = design_summary(net, structures)
    gap_m = vincenty_m(a.center_lat, a.center_lon, b.center_lat, b.center_lon)
    assert abs(s["column_count"] - gap_m / s["column_spacing_m"]) <= 1


def test_empty_network():
    s = design_summary(Network("empty"), {})
    assert (s["station_count"], s["circle_count"],
            s["route_miles"], s["column_count"]) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# Design report — segments, coverage, Markdown
# ---------------------------------------------------------------------------

from mesh_mobility.engine.design_report import design_report, network_signature


def test_segment_row_matches_route():
    net, structures, a, b = _station_and_circle()
    cps = {a.cp_id: a, b.cp_id: b}
    r = design_report(net, structures, cps)
    assert len(r["segments"]) == 1
    seg = r["segments"][0]
    assert abs(seg["length_mi"] - r["summary"]["route_miles"]) < 0.05


def test_coverage_single_station_is_walk_circle():
    import math
    net, structures, _, _ = _station_and_circle()
    r = design_report(net, structures, {})
    c = r["coverage"]
    expect = math.pi * (c["walk_m"] / 1000) ** 2
    assert abs(c["walk_km2"] - expect) / expect < 0.03
    assert c["bike_km2"] > c["walk_km2"]


def test_stale_travel_is_dropped():
    net, structures, _, _ = _station_and_circle()
    fresh = {"signature": network_signature(net), "pairs": 0}
    assert design_report(net, structures, {}, travel=fresh)["travel"] is fresh
    stale = {"signature": [0, 0], "pairs": 0}
    assert design_report(net, structures, {}, travel=stale)["travel"] is None


def test_markdown_tables_links_and_page_only_lines():
    from mesh_mobility.gui.report_md import html_to_markdown
    md = html_to_markdown(
        '<html><head><style>h1{color:red}</style></head><body>'
        '<h1>Title</h1><!--no-md--><div><p><a href="/api/x">JSON</a></p></div><!--/no-md-->'
        '<p>See <a href="/library">library</a> <strong>now</strong></p>'
        '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2 | 3</td></tr></table>'
        '</body></html>')
    assert md.startswith("# Title")
    assert "color:red" not in md and "JSON" not in md
    assert "[library](https://meshmobility.com/library) **now**" in md
    assert "| A | B |\n|---|---|\n| 1 | 2 \\| 3 |" in md
