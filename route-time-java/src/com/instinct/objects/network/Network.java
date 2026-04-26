package com.instinct.objects.network;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.WorkspaceManager;

public class Network implements Serializable {

	private static final long serialVersionUID = 1L;

	private Map<String, Line> lines = new HashMap<String, Line>();
	private Map<String, Node> nodes = new HashMap<String, Node>();
	private Map<String, NodeGroup> groups = new HashMap<String, NodeGroup>();

	private String name;
	private Line uncommitedLine = null;

	private Map<String, Line> boundaryLines = new HashMap<String, Line>();
	private Map<String, Node> boundaryNodes = new HashMap<String, Node>();

	private double lat, lon;

	private boolean isDirty = false;

	private long versionId;

	public long getVersionId() {
		return versionId;
	}

	public void setVersionId(long versionId) {
		this.versionId = versionId;
	}

	public Network(String name) {
		this.name = name;
	}

	public void addLine(Line line) {
		lines.put(line.getId(), line);
	}

	public void addNode(Node ps) {
		nodes.put(ps.getId(), ps);
		setDirty(true);

	}

	public void addBoundaryLine(Line line) {
		boundaryLines.put(line.getId(), line);
	}

	public void addBoundaryNode(Node ps) {
		boundaryNodes.put(ps.getId(), ps);
		setDirty(true);

	}

	public void addGroup(NodeGroup trafficCircle) {
		groups.put(trafficCircle.getId(), trafficCircle);
		setDirty(true);

	}

	public void removeGroup(String id) {
		groups.remove(id);
		setDirty(true);

	}

	public Line getLine(String id) {
		return lines.get(id);
	}

	public double getTotalLineLength() {
		double d = 0;
		for (Line l : lines.values()) {
			d = d + l.getLength();
		}
		return d;
	}

	public void clear() {
		nodes.clear();
		lines.clear();
		groups.clear();
		boundaryNodes.clear();
		boundaryLines.clear();
		uncommitedLine = null;
		setDirty(true);
		GlobalTimeKeeper.getInstance().reset();
	}

	public void computeMapCenter() {
		double total = 0;
		double latTotal = 0;
		double lonTotal = 0;
		for (Node st : getAllNodes()) {
			total++;
			latTotal += st.getLat();
			lonTotal += st.getLon();
		}
		this.lat = latTotal / total;
		this.lon = lonTotal / total;
	}

	public void deleteUncommitedLine() {
		this.uncommitedLine = null;
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (getClass() != obj.getClass())
			return false;
		Network other = (Network) obj;
		if (name == null) {
			if (other.name != null)
				return false;
		} else if (!name.equals(other.name))
			return false;
		return true;
	}

	public Collection<Line> getAllLines() {
		List<Line> allLines = new ArrayList<Line>();
		allLines.addAll(lines.values());
		if (uncommitedLine != null) {
			allLines.add(uncommitedLine);
		}
		return allLines;

	}

	public Collection<Node> getAllNodes() {
		return nodes.values();
	}

	public Collection<Station> getAllStations() {
		List<Station> stations = new ArrayList<Station>();
		for (Node n : nodes.values()) {
			if (n instanceof Station) {
				stations.add((Station) n);
			}
		}

		return stations;
	}

	private Collection<Drawable> getNearestNetworkNodes() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			if (node instanceof RenderableObject) {
				nodes.add(((RenderableObject) node).getUI());
			}
		}

		return nodes;
	}

	private Collection<Drawable> getNearestNonNetworkNodes() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllBoderNodes()) {
			if (node instanceof RenderableObject) {
				nodes.add(((RenderableObject) node).getUI());
			}
		}

		return nodes;
	}

	public double getLat() {
		return lat;
	}

	public Line getLine(Node start, Node end) {
		if (start instanceof Station) {
			Station st = (Station) start;
			if (st.getExit() != null && st.getExit().getEnd() != null && st.getExit().getEnd().getId().equals(end.getId())) {
				return st.getExit();
			} else {
				return null;
			}
		} else {
			Switch sw = (Switch) start;
			if (sw != null && end != null && sw.getExit1() != null && sw.getExit1().getEnd() != null && sw.getExit1().getEnd().getId().equals(end.getId())) {
				return sw.getExit1();
			} else if (sw != null && end != null && sw.getExit2() != null && sw.getExit2().getEnd() != null
					&& sw.getExit2().getEnd().getId().equals(end.getId())) {
				return sw.getExit2();
			} else {
				return null;
			}
		}
	}

	public double getLon() {
		return lon;
	}

	public String getName() {
		return name;
	}

	public Node getNearestNode(Coordinate c) {
		return getNearestNode(c.getLat(), c.getLon());
	}

	public Node getNearestNode(double lat, double lon) {
		Node st = null;
		double distance = java.lang.Double.MAX_VALUE;

		for (Node s : getAllNodes()) {
			double t = GeocodeUtil.distVincenty(lat, lon, s.getLat(), s.getLon());
			if (distance > t) {
				distance = t;
				st = s;
			}
		}
		return st;
	}

	public Node getNode(String id) {
		return nodes.get(id);
	}

	public Node getBoundaryNode(String id) {
		return boundaryNodes.get(id);
	}

	public Line getUncommitedLine() {
		return uncommitedLine;
	}

	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((name == null) ? 0 : name.hashCode());
		return result;
	}

	public boolean isDirty() {
		return isDirty;
	}

	public void safeKeeping() {
		for (Line line : getAllLines()) {
			line.getPodQueue().clear();
		}

		for (Station st : getAllStations()) {
			st.getPodQueue().clear();
			st.getPassengerQueue().clear();
			st.resetPodDepot();
		}

	}

	public void setDirty(boolean isDirty) {
		this.isDirty = isDirty;
	}

	public void setUncommitedLine(Node start) {
		this.uncommitedLine = new Line(start);
	}

	public String toString() {
		return name;
	}

	public void removeNode(Node node) {
		if (node == null) {
			return;
		}
		nodes.remove(node.getId());
		setDirty(true);

	}

	public void removeLine(Line line) {
		if (line == null) {
			return;
		}
		lines.remove(line.getId());
		setDirty(true);
	}

	public void removeBoundaryNode(Node node) {
		if (node == null) {
			return;
		}
		boundaryNodes.remove(node.getId());
		setDirty(true);

	}

	public void removeBoundaryLine(Line line) {
		if (line == null) {
			return;
		}
		boundaryLines.remove(line.getId());
		setDirty(true);
	}

	public Collection<Switch> getAllSwitchs() {
		List<Switch> switches = new ArrayList<Switch>();
		for (Node n : nodes.values()) {
			if (n instanceof Switch) {
				switches.add((Switch) n);
			}
		}

		return switches;
	}

	public NodeGroup getNodeGrp(String nodeGrpId) {
		if (groups.containsKey(nodeGrpId)) {
			return groups.get(nodeGrpId);
		} else {
			return null;
		}
	}

	public Collection<NodeGroup> getAllGroups() {
		return groups.values();
	}

	public Collection<Switch> getAllConvergences() {
		List<Switch> list = new ArrayList<Switch>();
		for (Node n : nodes.values()) {
			if (n instanceof Switch) {
				Switch sw = (Switch) n;
				if (sw.getEntryCount() == 2) {
					list.add(sw);
				}
			}
		}
		return list;
	}

	public Collection<Switch> getAllDivergences() {
		List<Switch> list = new ArrayList<Switch>();
		for (Node n : nodes.values()) {
			if (n instanceof Switch) {
				Switch sw = (Switch) n;
				if (sw.getExitCount() == 2) {
					list.add(sw);
				}
			}
		}
		return list;
	}

	public int getNumberOfNodeGroups() {
		return this.groups.size();
	}

	public Station getRandomStation(Station exclude) {
		List<Station> sts = new ArrayList<Station>(getAllStations());
		int index = (int) ((int) sts.size() * Math.random());
		Station st = sts.get(index);
		while (st.getId().equals(exclude.getId())) {
			index = (int) ((int) sts.size() * Math.random());
			st = sts.get(index);
		}
		return st;
	}

	public Collection<NodeGroup> getNonStationGroups() {
		List<NodeGroup> values = new ArrayList<NodeGroup>();
		for (NodeGroup ng : groups.values()) {
			if (ng instanceof NodeGroupImpl) {
				values.add(ng);
			}
		}
		return values;
	}

	public Collection<Node> getAllBoderNodes() {
		return boundaryNodes.values();
	}

	public Collection<Line> getAllBorderLines() {
		return boundaryLines.values();
	}

	public int getTotalPods() {
		int totalPods=0;
		for (Station st : getAllStations()) {
			totalPods = totalPods + st.getPodExpended();
		}
		return totalPods;
	}

}
