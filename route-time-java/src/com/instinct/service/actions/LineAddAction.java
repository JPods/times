package com.instinct.service.actions;

import java.awt.Point;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.ActionManager;
import com.instinct.service.WorkspaceManager;

public class LineAddAction implements Action {

	private Line line = null;
	private Switch start, end;
	private boolean isStartNodeAdded = false, isEndNodeAdded = false;
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
			line.setNetworkElement(true);
			WorkspaceManager.getInstance().getNetwork().addLine(line);
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
			if (end.isComplete() == false) {
				WorkspaceManager.getInstance().getNetwork().setUncommitedLine(end);
			} else {
				ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getLineAddFac());
			}
		}
		return null;
	}

	private boolean checkConsistency() {
		if (start == null || end == null) {
			return false;
		}

		if (start.getId().equals(end.getId())) {
			return false;
		}
		if (lineDoesnExist() == false) {
			Pad.getInstance().showAlert("Line already exists");
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
		
		if(end.isNetworkElement()==false || start.isNetworkElement()==false) {
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

		Drawable<? extends Node> endNode = pad.getNearestNetworkNode(p,30);
		if (endNode == null) {
			end = new SwitchImpl();
			Coordinate c = pad.getPosition(p);
			((Node) end).setPosition(c);
			WorkspaceManager.getInstance().getNetwork().addNode(end);
			isEndNodeAdded = true;

		} else {
			if (endNode.getId().equals(start.getId()) && notInSameNodeGroup(start, end)) {
				end = null;
			} else {
				endNode.setGlow(false);
				end = (Switch) endNode.getModel();
			}
		}
	}

	private boolean notInSameNodeGroup(Switch start2, Switch end2) {
		if (start2.getNodeGroup() != null && end2.getNodeGroup() != null && start2.getNodeGroup().getId().equals(end2.getNodeGroup().getId())) {
			return false;
		}
		return true;

	}

	@Override
	public void undo() {
		line.remove();
		if (isEndNodeAdded) {
			Node n = (Node) end;
			if (WorkspaceManager.getInstance().getNetwork().getNode(n.getId()) != null) {
				((Switch) end).remove();
			} else {
				Point p = Pad.getInstance().getMapPosition(n.getLat(), n.getLon());
				Drawable<?> d = Pad.getInstance().getNodeAt(p);
				if (d != null) {
					n = (Node) d.getModel();
					n.remove();
				}
			}
		}
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
		Drawable<? extends Node> d = pad.getNearestNetworkNode(p);
		if (d != null) {
			return d.getModel();
		}

		Coordinate c = Pad.getInstance().getPosition(p);
		Node st = WorkspaceManager.getInstance().getNetwork().getNearestNode(c);
		if (st == null) {
			return addStartNode(p);
		} else {
			Point p1 = Pad.getInstance().getMapPosition(st.getLat(), st.getLon());
			if (p1 != null && p.distance(p1) < 15) {
				return st;
			} else {
				return addStartNode(p);
			}
		}
	}

	private Node addStartNode(Point p) {
		Coordinate c = Pad.getInstance().getPosition(p);
		SwitchImpl sw=new SwitchImpl(c.getLat(), c.getLon());
		sw.setNetworkElement(true);
		this.isStartNodeAdded=true;
		WorkspaceManager.getInstance().getNetwork().addNode(sw);
		return sw;
	}

	private boolean isStartNodeAllowed(Node startNode) {
		if(startNode instanceof Station) {
			return false;
		}
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
