package com.instinct.service.actions;

import java.awt.Point;

import javax.swing.JOptionPane;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.StationGroup;
import com.instinct.objects.network.Switch;
import com.instinct.service.WorkspaceManager;

public class MarkStationAction implements Action {

	private Switch entryNode, exitNode;
	private Coordinate c;
	private Switch sw;
	private StationGroup tc;
	private final int MIN_GAP=25;

	public void init(Point p) {
		Drawable<?> d=Pad.getInstance().getNearestNetworkNode(p);
		if(d==null || d.getModel() instanceof Station) {
			return;
		}
		sw=(Switch) d.getModel();
		Line line=sw.getEntry();
		entryNode = (Switch) line.getStart();
		exitNode = (Switch) sw.getExit().getEnd();
		c = new Coordinate(((Node) sw).getLat(), ((Node) sw).getLon());
	}

	@Override
	public Object execute(Point p) {
		if(sw.getEntry().getLength()<MIN_GAP || sw.getExit().getLength()<MIN_GAP) {
			Pad.getInstance().showAlert("Entry/Exit line too short");
			return null;
		}
		tc = new StationGroup(sw);
		WorkspaceManager.getInstance().getNetwork().addGroup(tc);
		sw.remove();
		return null;
	}

	@Override
	public void undo() {
		Pad.getInstance().showAlert("Station undo not supported, use delete");
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		if (isClickedOnEntryExitNode(pad, p) && validateSwitchIsGood(pad, p)) {
			pad.setHighlight(null);
			return true;

		}
		return false;
	}

	private boolean isClickedOnEntryExitNode(Pad pad, Point p) {
		Drawable<?> h = pad.getNodeAt(p);
		if (h != null) {
			return (h.getModel() instanceof Switch);
		}
		return false;

	}

	private boolean validateSwitchIsGood(Pad pad, Point p) {
		Node n=pad.getNodeAt(p).getModel();
		Switch sw = (Switch) n;
		if (sw.getEntry() == null || sw.getExit() == null) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Only switches with entry and exit lines can be changed to Station", "Station check",
					JOptionPane.INFORMATION_MESSAGE, null);
			return false;
		} else if (n.isNodeGroup()) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Only switches outside Node Group can be marked as Station", "Station check",
					JOptionPane.INFORMATION_MESSAGE, null);
			return false;
		}
		return true;
	}


	@Override
	public boolean isDone() {
		return true;
	}

	@Override
	public void abort() {
		// TODO Auto-generated method stub
		
	}

}
