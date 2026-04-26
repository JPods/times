package com.instinct.service.actions;

import java.awt.Point;

import javax.swing.JOptionPane;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.TrafficCircle;
import com.instinct.service.WorkspaceManager;

public class CircleAddAction implements Action<Object> {

	private Point p = null;
	private String id = null;

	public void init(Point p) {
		this.p = p;
	}

	@Override
	public Object execute(Point p) {
		Pad pad = Pad.getInstance();
		Coordinate c = pad.getPosition(p);

		TrafficCircle tc = new TrafficCircle(c);
		WorkspaceManager.getInstance().getNetwork().addGroup(tc);
		this.id = tc.getId();
		return null;
	}

	@Override
	public void undo() {
		WorkspaceManager.getInstance().getNetwork().removeGroup(id);

	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		
		Coordinate c = pad.getPosition(p);
		boolean isAllowed = isAllowed(c);
		if (!isAllowed) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Very close to adjacent station", "Station check", JOptionPane.INFORMATION_MESSAGE, null);
			return false;
		}
		pad.setHighlight(null);
		return true;
	}

	private boolean isAllowed(Coordinate c) {
		int closeness = 25;
		for (Node n : WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			double d = GeocodeUtil.distVincenty(c, new Coordinate(n.getLat(), n.getLon()));
			if (closeness > d) {
				JOptionPane.showMessageDialog(MainFrame.getInstance(), "Very close to adjacent switch", "Switch check", JOptionPane.INFORMATION_MESSAGE, null);
				return false;
			}
		}
		return true;
	}


	@Override
	public boolean isDone() {
		return true;
	}

	@Override
	public void abort() {
	}
}
