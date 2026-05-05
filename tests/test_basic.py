"""
Smoke tests — run with:  python -m pytest route_time/tests/ -v
"""
import os
import sys
import pytest

# Allow importing route_time from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from route_time.engine import Network, Node, Line, Simulator, find_path_by_id
from route_time.engine.physics import PhysicsModel

SCALE_MAP = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "jpod_OS", "mapSM.json"
)
JPD_EXAMPLE = "/Applications/RouteTime_JPods/OK_Tulsa_01.jpd"


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------

class TestPhysics:
    def setup_method(self):
        self.p = PhysicsModel({"maxVelocityInKMPH": 60, "accInG": 1.0, "deccInG": 1.0,
                                "timeResolutionPerSec": 9})

    def test_transit_time_positive(self):
        t = self.p.transit_time_ms(1000)
        assert t > 0

    def test_transit_time_short_line(self):
        # Short line — no cruise phase
        t_short = self.p.transit_time_ms(10)
        t_long  = self.p.transit_time_ms(1000)
        assert t_short < t_long

    def test_cruise_speed(self):
        assert abs(self.p.max_v_m_s - 60 * 1000 / 3600) < 0.001


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:
    def setup_method(self):
        # Build a tiny 3-node network: A → B → C
        self.net = Network(network_id="test")
        nA = Node("A", 0.0, 0.0)
        nB = Node("B", 0.0, 0.001)
        nC = Node("C", 0.0, 0.002)
        for n in [nA, nB, nC]:
            self.net.nodes[n.node_id] = n
        lAB = Line("AB", nA, nB, 100.0)
        lBC = Line("BC", nB, nC, 100.0)
        for l in [lAB, lBC]:
            self.net.lines[l.line_id] = l
        self.net.build()

    def test_direct_path(self):
        path = find_path_by_id(self.net, "A", "C")
        assert [l.line_id for l in path] == ["AB", "BC"]

    def test_no_path_reverse(self):
        # Directed — no path from C to A
        path = find_path_by_id(self.net, "C", "A")
        assert path == []

    def test_same_node(self):
        path = find_path_by_id(self.net, "A", "A")
        assert path == []


# ---------------------------------------------------------------------------
# JPD reader
# ---------------------------------------------------------------------------

class TestJpdReader:
    @pytest.mark.skipif(not os.path.exists(JPD_EXAMPLE), reason="jpd example not found")
    def test_load_ok_tulsa(self):
        from route_time.io import load_jpd
        net, _, _, _ = load_jpd(JPD_EXAMPLE)
        assert len(net.nodes) > 0
        assert len(net.lines) > 0
        assert len(net.stations) > 0
        assert net.total_length_m() > 0

    @pytest.mark.skipif(not os.path.exists(JPD_EXAMPLE), reason="jpd example not found")
    def test_all_lines_have_length(self):
        from route_time.io import load_jpd
        net, _, _, _ = load_jpd(JPD_EXAMPLE)
        for line in net.lines.values():
            assert line.length_m > 0, f"Line {line.line_id} has zero length"


# ---------------------------------------------------------------------------
# Scale map reader
# ---------------------------------------------------------------------------

class TestMapReader:
    @pytest.mark.skipif(not os.path.exists(SCALE_MAP), reason="scale map not found")
    def test_load_scale_map(self):
        from route_time.io import load_podpresenter
        net = load_podpresenter(SCALE_MAP)
        assert len(net.lines) == 3
        assert len(net.stations) > 0

    @pytest.mark.skipif(not os.path.exists(SCALE_MAP), reason="scale map not found")
    def test_scale_map_lengths(self):
        from route_time.io import load_podpresenter
        net = load_podpresenter(SCALE_MAP)
        # Line 1 should be ~836mm = 0.836m
        line1 = net.lines.get("1")
        assert line1 is not None
        assert 0.8 < line1.length_m < 0.9, f"Expected ~0.836m, got {line1.length_m}"


# ---------------------------------------------------------------------------
# Simulation — tiny network
# ---------------------------------------------------------------------------

class TestSimulator:
    def _build_loop_network(self) -> Network:
        """Two stations connected by two lines (CCW loop)."""
        from route_time.engine import Station
        net = Network(network_id="loop")
        nA = Node("SA", 0.0, 0.0, is_station=True)
        nB = Node("SB", 0.0, 0.01, is_station=True)
        net.nodes["SA"] = nA
        net.nodes["SB"] = nB
        net.stations["SA"] = Station("SA", nA)
        net.stations["SB"] = Station("SB", nB)
        lAB = Line("AB", nA, nB, 500.0)
        lBA = Line("BA", nB, nA, 500.0)
        net.lines["AB"] = lAB
        net.lines["BA"] = lBA
        net.build()
        return net

    def test_simulation_runs(self):
        net = self._build_loop_network()
        settings = {"maxVelocityInKMPH": 60, "accInG": 1.0, "deccInG": 1.0,
                    "timeResolutionPerSec": 9, "podsPerStation": 2, "graceDistance": 0}
        sim = Simulator(net, settings)
        result = sim.run(total_slots=10)
        assert result.passengers_generated > 0

    def test_simulation_records_transit_times(self):
        net = self._build_loop_network()
        settings = {"maxVelocityInKMPH": 60, "accInG": 1.0, "deccInG": 1.0,
                    "timeResolutionPerSec": 9, "podsPerStation": 2, "graceDistance": 0}
        sim = Simulator(net, settings)
        sim.run(total_slots=20)
        # At least one line should have transit samples
        has_samples = any(
            len(l.transit_samples_ms) > 0 for l in net.lines.values()
        )
        assert has_samples
