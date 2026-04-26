package com.instinct.service;

import java.util.ArrayList;
import java.util.List;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.SwitchImpl;

public class NetworkValidator {

	
	public String getValidationString() {
		List<String> s1 = getIncompleteNodes();
		List<String> s2 = getIncompleteLines();
		String s3 = getIncomplePaths();
		if (s1.size() > 0) {
			return "List of incomplete Switches:" + s1;
		} else if (s2.size() > 0) {
			return "List of incomplete Lines:" + s2;
		} else if (s3.length() > 0) {
			return "List of incomplete Paths:" + s3;
		} else {
			return null;
		}
	}

	private String getIncomplePaths() {
		List<Station> sts = new ArrayList<Station>(WorkspaceManager.getInstance().getNetwork().getAllStations());
		RouteTableService.getInstance().recompute();
		StringBuilder sb = new StringBuilder();
		for (int i = 0; i < sts.size(); i++) {
			for (int j = 0; j < sts.size(); j++) {
				Station src = sts.get(i);
				Station dest = sts.get(j);
				if (src.equals(dest)) {
					continue;
				}
				String row[] = new String[3];
				row[0] = src.getId();
				row[1] = dest.getId();
				List<Node> list = getPathText(src, dest);
				if (list == null || list.size() == 0) {
					sb.append("No path exists from " + src.getId() + " to " + dest.getId());
					sb.append("\n");
				}
			}
		}
		return sb.toString();
	}

	private List<String> getIncompleteNodes() {
		List<String> incompleteNodes = new ArrayList<String>();
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			if (node instanceof SwitchImpl) {
				SwitchImpl sw = (SwitchImpl) node;
				if (sw.getEntryCount() == 0 || sw.getExitCount() == 0 || (sw.getEntryCount() == 2 && sw.getExitCount() == 2)) {
					incompleteNodes.add(sw.getId());
				}
			} else if (node instanceof Station) {
				Station st = (Station) node;
				if (st.getEntry() == null || st.getExit() == null) {
					incompleteNodes.add(st.getId());
				}
			}
		}
		return incompleteNodes;
	}

	private List<String> getIncompleteLines() {
		List<String> incompleteLines = new ArrayList<String>();
		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			if (line.getStart() == null || line.getEnd() == null) {
				incompleteLines.add(line.getId());
			}
		}
		return incompleteLines;
	}
	
	private List<Node> getPathText(Station src, Station dest) {
		List<Node> path = RouteTableService.getInstance().getPathNodes(src, dest);
		return path;
	}
}
