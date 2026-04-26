package com.instinct.service.actions;

import java.awt.Point;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.WorkspaceManager;

public class DoubleLineAddAction implements Action {

	private static final double DISTANCE = 25;
	private Line line = null;
	private Switch start, end, reverseStart;
	private boolean isStartForwardNodeAdded = false;
	private boolean isEndBackwardNodeAdded = false;
	private boolean isDone;
	private Line reverseLine;

	public void init(Point p) {
	}

	@Override
	public Object execute(Point p) {
		Pad pad = Pad.getInstance();
		Network net = WorkspaceManager.getInstance().getNetwork();
		if (net.getUncommitedLine() == null) {
			WorkspaceManager.getInstance().getNetwork().setUncommitedLine((Node) start);
			line = net.getUncommitedLine();
			return null;
		} else {
			line=net.getUncommitedLine();
			start=(Switch)line.getStart();
		}
		Drawable<? extends Node> endNode = pad.getNodeAt(p);
		if(endNode!=null && endNode.getId().equals(start.getId())) {
			return null;
		}
		setEnd(pad, p);
		boolean isAdded=false;
		if (checkConsistency()) {
			line.setEnd((Node) end);
			end.attachEntryLine(line);
			start.attachExitLine(line);
			WorkspaceManager.getInstance().getNetwork().addLine(line);
			drawReverse(start, end);
			isAdded=true;
		} else {
			line.remove();
			if (isStartForwardNodeAdded) {
				((Node) end).remove();
			}
		}
		WorkspaceManager.getInstance().getNetwork().deleteUncommitedLine();
		isDone = true;
		if(isAdded) {
			WorkspaceManager.getInstance().getNetwork().setUncommitedLine(end);
		}
		return null;
	}
	
	private boolean checkConsistency() {
		if(start==null || end==null) {
			return false;
		}
		
		if(start.getId().equals(end.getId())) {
			return false;
		}
		
		if(lineDoesnExist()==false) {
			Pad.getInstance().showAlert("Line already exists");
			return false;
		}
		if(end.checkValidEntry()==false) {
			Pad.getInstance().showAlert("Entry Node have no room");
			return false;
		}
		if(start.checkValidExit()==false) {
			Pad.getInstance().showAlert("Exit Node has no room");
			return false;
		}
		return true;
	}
	
	private boolean lineDoesnExist() {
		Line l1 = WorkspaceManager.getInstance().getNetwork().getLine(start, end);
		Line l2 = WorkspaceManager.getInstance().getNetwork().getLine(end, start);
		if (l1 == null && l2 == null) {
			return true;
		} else {
			return false;
		}
	}

	private void setEnd(Pad pad, Point p) {
		Drawable<? extends Node> endNode = pad.getNodeAt(p);
		if (endNode == null) {
			end = new SwitchImpl();
			Coordinate c = pad.getPosition(p);
			((Node) end).setPosition(c);
			WorkspaceManager.getInstance().getNetwork().addNode((Node) end);
			isStartForwardNodeAdded = true;

		} else {
			end = (Switch) endNode.getModel();
		}
		
	}

	private void drawReverse(Switch start, Switch end) {
		Switch closestToStart=getClosestNode(start);
		if(closestToStart==null) {
			closestToStart = new SwitchImpl();
			WorkspaceManager.getInstance().getNetwork().addNode(closestToStart);
		}
		closestToStart.setPosition(start.getLat()-0.00005, start.getLon());
		
		
		reverseStart = new SwitchImpl();
		WorkspaceManager.getInstance().getNetwork().addNode(reverseStart);
		reverseStart.setPosition(end.getLat()-0.00005, end.getLon());
		reverseLine=new Line(reverseStart);
		closestToStart.attachEntryLine(reverseLine);
		reverseStart.attachExitLine(reverseLine);
		reverseLine.setEnd(closestToStart);
		WorkspaceManager.getInstance().getNetwork().addLine(reverseLine);
	}

	private Switch getClosestNode(Switch start) {
		for(Node n:WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			double d=GeocodeUtil.distVincity(start, n);
			if(d<DISTANCE && n.isNodeGroup()!=true && !start.equals(n)) {
				return (Switch)n;
			}
		}
		return null;
	}

	@Override
	public void undo() {
		line.remove();
		reverseLine.remove();
		if (isStartForwardNodeAdded) {
			if (WorkspaceManager.getInstance().getNetwork().getNode(end.getId()) != null) {
				((Switch) end).remove();
			} else {
				Point p = Pad.getInstance().getMapPosition(end.getLat(), end.getLon());
				Drawable<?> d = Pad.getInstance().getNodeAt(p);
				if (d != null) {
					Node n = (Node) d.getModel();
					n.remove();
				}
			}
		}
		
		if (isEndBackwardNodeAdded) {
			Node n = (Node) reverseLine.getEnd();
			if (WorkspaceManager.getInstance().getNetwork().getNode(n.getId()) != null) {
				((Switch) n).remove();
			} else {
				Point p = Pad.getInstance().getMapPosition(n.getLat(), n.getLon());
				Drawable<?> d = Pad.getInstance().getNodeAt(p);
				if (d != null) {
					n = (Node) d.getModel();
					n.remove();
				}
			}
		}
		
		reverseStart.remove();
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		if (start == null &&  net.getUncommitedLine()==null) {
			Node startNode = getStartNode(pad, p);
			if (startNode != null && isStartNodeAllowed(startNode)) {
				this.start = (Switch) startNode;
				return true;
			} else {
				return false;
			}
		} else {
			return true;
		}
	}

	private Node getStartNode(Pad pad, Point p) {
		Node startNode = null;
		Drawable<? extends Node> d = pad.getNodeAt(p);
		if (d != null) {
			startNode = d.getModel();
			return startNode;
		}

		Coordinate c = Pad.getInstance().getPosition(p);
		Node st = WorkspaceManager.getInstance().getNetwork().getNearestNode(c);
		if(st==null) {
			return null;
		}
		Point p1 = Pad.getInstance().getMapPosition(st.getLat(), st.getLon(),false);
		if (p1 != null && p.distance(p1) < 15) {
			return startNode;
		} else {
			return null;
		}
	}

	private boolean isStartNodeAllowed(Node startNode) {
		return ((Switch) startNode).getExitCount() < 2;
	}

	@Override
	public boolean isDone() {
		return isDone;
	}

	@Override
	public void abort() {
		isDone = true;
		WorkspaceManager.getInstance().getNetwork().deleteUncommitedLine();
	}

}