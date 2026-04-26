package com.instinct.service.dijkstra;

import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;

import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.service.RouteTableService;
import com.instinct.service.WorkspaceManager;

public class MergeLoadCalculator {

	private Map<String, Integer> mergeLoads = new HashMap<String, Integer>();

	private static MergeLoadCalculator instance = new MergeLoadCalculator();

	public static MergeLoadCalculator getInstance() {
		return instance;
	}

	private void initialize(Collection<Switch> allNodes) {
		for (Switch sw : allNodes) {
			//if (sw instanceof Station) {
				mergeLoads.put(sw.getId(), 0);
			//}
		}
	}

	public void calc(Station[] stations) {
		initialize(WorkspaceManager.getInstance().getNetwork().getAllConvergences());
		int totalRoutes = 0;
		for (int i = 0; i < stations.length; i++) {
			Station start = stations[i];
			for (int k = 0; k < stations.length; k++) {
				Station end = stations[k];
				if (i != k) {
					compute(start, end);
					compute(end, start);
					totalRoutes += 2;
				}
			}
		}
		
		for(Map.Entry<String, Integer> entrySet:mergeLoads.entrySet()) {
			normalize(entrySet, stations.length);
		}
		System.out.println("Total Routes:" + totalRoutes);
		System.out.println(mergeLoads);
	}

	private void normalize(Entry<String, Integer> e, int length) {
		e.setValue(e.getValue()/(length*2));
	}

	private void compute(Station end, Station start) {
		List<Node> path = RouteTableService.getInstance().getPathNodes(start, end);

		for (Node n : path) {
			if (mergeLoads.containsKey(n.getId())) {
				mergeLoads.put(n.getId(), mergeLoads.get(n.getId()) + 1);
			}
		}
	}

	public int getLoad(String mergeNodeId) {
		return mergeLoads.get(mergeNodeId);
	}
}
