package com.instinct.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.service.dijkstra.RouteFinder;

public class RouteTableService {

	private Map<Node, RouteFinder> rts = new HashMap<Node, RouteFinder>();


	private static RouteTableService instance = new RouteTableService();

	
	public static RouteTableService getInstance() {
		return instance;
	}

	private RouteTableService() {
	}


	

	public synchronized void recompute() {
		Map<Node, RouteFinder> temp = new HashMap<Node, RouteFinder>();
		List<Node> nodes = new ArrayList<Node>(WorkspaceManager.getInstance().getNetwork().getAllNodes());
		for (Node n : nodes) {
			RouteFinder rt = new RouteFinder();
			rt.execute(n);
			temp.put(n, rt);
		}
		updateTable(temp);
		
		
	}

	public synchronized void updateTable(Map<Node, RouteFinder> temp) {
		rts = temp;
	}


	public synchronized List<Node> getPathNodes(Node src, Node dest) {
		RouteFinder rt = rts.get(src);
		List<Node> nodes = rt.getPath(dest);
		return nodes;
	}

	public synchronized List<Line> getPath(Node src, Node dest) {
		RouteFinder rt = rts.get(src);
		List<Node> nodes = rt.getPath(dest);
		List<Line> lines = new ArrayList<Line>();
		if(nodes==null || nodes.size()<2) {
			return lines;
		}
		Node start = nodes.get(0);
		for (int i = 1; i < nodes.size(); i++) {
			Node end = nodes.get(i);
			Line line = WorkspaceManager.getInstance().getNetwork().getLine(start, end);
			lines.add(line);
			start = end;
		}
		return lines;
	}
	
	public synchronized Node getNextNode(Node src, Node dest) {
		RouteFinder rt = rts.get(src);
		if (rt == null) {
			return null;
		}
		List<Node> nodes = rt.getPath(dest);
		if (nodes == null) {
			return null;
		}
		Node n= nodes.get(1);
		return n;
	}
}

