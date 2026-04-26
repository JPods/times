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
import com.instinct.service.WorkspaceManager;

public class SwitchAddAction implements Action<Node> {

	private Point p = null;
	private Switch newNode;
	private Line line, newLine;

	public void init(Point p) {
		this.p = p;
		Drawable d = Pad.getInstance().getClosestLine(p, 3);
		if (d != null && d.getModel() instanceof Line) {
			this.line = (Line) d.getModel();
		}
	}

	@Override
	public Node execute(Point p) {
		if (line != null && line.isNetworkElement()==false) {
				return null;
		}
		Pad pad = Pad.getInstance();
		Coordinate c = pad.getPosition(p);
		newNode = new SwitchImpl();
		newNode.setPosition(c.getLat(), c.getLon());

		WorkspaceManager.getInstance().getNetwork().addNode(newNode);
		if (line != null) {
			split(newNode);
		}

		return newNode;
	}

	@Override
	public void undo() {
		if (line != null) {
			Node sw = newLine.getEnd();
			newLine.remove();
			newNode.remove();
			line.setEnd(sw);
			((Switch) sw).attachEntryLine(line);
		}
		if (WorkspaceManager.getInstance().getNetwork().getNode(newNode.getId()) != null) {
			newNode.remove();
		} else {
			Point p = Pad.getInstance().getMapPosition(newNode.getLat(), newNode.getLon());
			if (Pad.getInstance().getNodeAt(p) != null) {
				Node n = Pad.getInstance().getNodeAt(p).getModel();
				n.remove();
			}
		}
	}

	public void split(Switch node) {
		Switch end = (Switch) line.getEnd();

		end.detachEntryLine(line);

		newLine = new Line(node);
		newLine.setEnd(line.getEnd());
		line.setEnd(node);

		node.attachEntryLine(line);
		node.attachExitLine(newLine);
		end.attachEntryLine(newLine);

		WorkspaceManager.getInstance().getNetwork().addLine(newLine);
		line.recomputeLength();
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		Drawable d = pad.getHighligtableAt(p);
		if (d == null) {
			return true;
		} else if (d.getModel() instanceof Line) {
			Line line = (Line) d.getModel();
			if (line.getStart().isNodeGroup() && line.getEnd().isNodeGroup()) {
				if (line.getStart().getNodeGroup().getId().equals(line.getEnd().getNodeGroup().getId())) {
					return false;
				} else {
					return true;
				}

			} else {
				return true;
			}
		}
		return false;
	}

	@Override
	public boolean isDone() {
		return true;
	}

	@Override
	public void abort() {
	}

}
