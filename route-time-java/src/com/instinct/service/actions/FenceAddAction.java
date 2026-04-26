package com.instinct.service.actions;

import java.awt.Point;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.ActionManager;
import com.instinct.service.WorkspaceManager;

public class FenceAddAction implements Action {

	private Line line = null;
	private Switch start, end;
	private boolean isEndNodeAdded=false, isStartNodeAdded = false;
	private boolean isDone;

	public void init(Point p) {
	}

	@Override
	public Object execute(Point p) {
		boolean isAdded = false;
		Pad pad = Pad.getInstance();
		Network net = WorkspaceManager.getInstance().getNetwork();
		if (net.getUncommitedLine() == null) {
			WorkspaceManager.getInstance().getNetwork().setUncommitedLine((Node) start);
			line = net.getUncommitedLine();
			line.setNetworkElement(false);
			return null;
		} else {
			line = net.getUncommitedLine();
			start = (Switch) line.getStart();
		}
		setEnd(pad, p);

		if (checkConsistency()) {
			line.setEnd((Node) end);
			end.attachEntryLine(line);
			start.attachExitLine(line);
			line.setNetworkElement(false);
			start.setNetworkElement(false);
			end.setNetworkElement(false);
			WorkspaceManager.getInstance().getNetwork().addBoundaryLine(line);
			isAdded = true;
		} else {
			line.remove();
			if (isEndNodeAdded) {
				((Node) end).remove();
			}
			
			if(isStartNodeAdded) {
				start.remove();
			}
		}
		
		WorkspaceManager.getInstance().getNetwork().deleteUncommitedLine();
		isDone = true;
		if (isAdded) {
			if(end.isComplete()==false) {
				WorkspaceManager.getInstance().getNetwork().setUncommitedLine(end);
				WorkspaceManager.getInstance().getNetwork().getUncommitedLine().setNetworkElement(false);
			} else {
				ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getFenceAddFac());
			}
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
		if (lineDoesnExist() == false) {
			Pad.getInstance().showAlert("Line already exists");
			return false;
		}
		
		if(end.isNetworkElement() || start.isNetworkElement()) {
			Pad.getInstance().showAlert("Can't draw border with network switches");
			return false;
		}
		
		if (end.checkValidEntry() == false) {
			Pad.getInstance().showAlert("Entry Node have no room");
			return false;
		}
		if (start.checkValidExit() == false) {
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

		Drawable<? extends Node> endNode = pad.getNearestNonNetworkNode(p);
		if (endNode == null) {
			end = new SwitchImpl();
			Coordinate c = pad.getPosition(p);
			((Node) end).setPosition(c);
			WorkspaceManager.getInstance().getNetwork().addBoundaryNode(end);
			end.setNetworkElement(false);
			isEndNodeAdded = true;
		} else if (endNode.getId().equals(start.getId())) {
			end = null;
		} else {
			endNode.setGlow(false);
			end = (Switch) endNode.getModel();
		}
	}

	@Override
	public void undo() {
		Switch sw=(Switch)line.getStart();
		if(sw.getEntryCount()==0) {
			WorkspaceManager.getInstance().getNetwork().removeBoundaryNode(line.getStart());
		}
		
		sw=(Switch)line.getEnd();
		WorkspaceManager.getInstance().getNetwork().removeBoundaryNode(line.getEnd());
		WorkspaceManager.getInstance().getNetwork().removeBoundaryLine(line);
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		if (start == null && net.getUncommitedLine() == null) {
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
			if(startNode instanceof Switch) {
				return startNode;
			}
		}

		Coordinate c = Pad.getInstance().getPosition(p);
		SwitchImpl sw=new SwitchImpl(c.getLat(), c.getLon());
		sw.setNetworkElement(false);
		this.isStartNodeAdded=true;
		WorkspaceManager.getInstance().getNetwork().addBoundaryNode(sw);
		return sw;
	}

	private boolean isStartNodeAllowed(Node startNode) {
		Switch sw=(Switch)startNode;
		if(sw.isNetworkElement()==false && sw.getExitCount()<2){
			return true;
		}
		return false;
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
