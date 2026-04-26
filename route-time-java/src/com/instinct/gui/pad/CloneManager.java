package com.instinct.gui.pad;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.NodeGroupImpl;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;

public class CloneManager {

	private Map<String, String> originalIdToCloneId = new HashMap<String, String>();
	private Map<String, Set<String>> nodeGroups = new HashMap<String, Set<String>>();
	private Map<String, Node> clonedNodes = new HashMap<String, Node>();
	private List<Line> clonedLines = new ArrayList<Line>();
	private List<NodeGroup> clonedNodeGroups = new ArrayList<NodeGroup>();
	private double latOffset;
	private double lonOffset;

	public void clone(Collection<Node> nodes, double latOffset, double lonOffset) {
		this.latOffset = latOffset;
		this.lonOffset = lonOffset;
		cloneNodes(nodes);
		getLinks(nodes);
		mapGroups(nodes);
		getGroups();
	}

	public void addToNetwork(Network net) {
		for (Node n : clonedNodes.values()) {
			net.addNode(n);
		}

		for (Line line : clonedLines) {
			net.addLine(line);
		}

		for (NodeGroup ng : clonedNodeGroups) {
			net.addGroup(ng);
		}
	}

	public Collection<Node> getClones() {
		return clonedNodes.values();
	}

	private void getGroups() {
		for (Map.Entry<String, Set<String>> e : nodeGroups.entrySet()) {
			NodeGroupImpl ng = new NodeGroupImpl();
			for (String id : e.getValue()) {
				ng.addNode(clonedNodes.get(id));
				clonedNodes.get(id).setNodeGroup(ng);
			}
			clonedNodeGroups.add(ng);
		}
	}

	private void mapGroups(Collection<Node> nodes) {
		for (Node n : nodes) {
			if (n.getNodeGroup() != null) {
				if (nodeGroups.containsKey(n.getNodeGroup().getId()) == false) {
					nodeGroups.put(n.getNodeGroup().getId(), new HashSet<String>());
				}
				nodeGroups.get(n.getNodeGroup().getId()).add(originalIdToCloneId.get(n.getId()));
			}
		}

	}

	private void cloneNodes(Collection<Node> nodes) {
		for (Node n : nodes) {
			Node clone = n.clone();
			clone.setPosition(clone.getLat() + latOffset, clone.getLon() + lonOffset);
			clonedNodes.put(clone.getId(), clone);
			originalIdToCloneId.put(n.getId(), clone.getId());
		}
	}

	private void getLinks(Collection<Node> nodes) {
		for (Node n : nodes) {
			if (n instanceof Station) {
				Station st = (Station) n;
				getLink(st.getExit());

			} else {
				Switch sw = (Switch) n;
				getLink(sw.getExit1());
				getLink(sw.getExit2());
			}
		}
	}


	private void getLink(Line line) {
		if (line == null || line.getStart() == null || line.getEnd() == null) {
			System.out.println(line + " is null");
			return;
		}
		String newStartId = originalIdToCloneId.get(line.getStart().getId());
		String newEndId = originalIdToCloneId.get(line.getEnd().getId());
		if (newStartId == null || newEndId == null) {
			System.out.println("Ids are null. NewStartId:" + newStartId + ", NewEndId:" + newEndId);
			return;
		}
		Node newStart=clonedNodes.get(newStartId);
		if(newStart==null) {
			System.out.println("New Start Node is null");
		}
		
		Node newEnd=clonedNodes.get(newEndId);
		if(newEnd==null) {
			System.out.println("New End is null");
			return;
		}
		Line clonedLine = new Line(newStart);
		clonedLine.setEnd(newEnd);

		clonedLines.add(clonedLine);
		
		attachLineToEndPoints(newStart, newEnd, clonedLine);

	}

	private void attachLineToEndPoints(Node newStart, Node newEnd, Line clonedLine) {
		if(newStart instanceof Station)  {
			Station st=(Station)newStart;
			st.setExit(clonedLine);
		} else if(newStart instanceof Switch)  {
			Switch sw=(Switch)newStart;
			sw.attachExitLine(clonedLine);
		}
		
		if(newEnd instanceof Station)  {
			Station st=(Station)newEnd;
			st.setEntry(clonedLine);
		} else if(newEnd instanceof Switch)  {
			Switch sw=(Switch)newEnd;
			sw.attachEntryLine(clonedLine);
		}
	}
}
