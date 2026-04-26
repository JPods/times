package com.instinct.service;

import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.TimeGraph;
import com.instinct.gui.pad.Pad;

public class TimeGraphMouseHandler implements MouseListener {

	private static TimeGraphMouseHandler instance=new TimeGraphMouseHandler();
	
	public static TimeGraphMouseHandler getInstance() {
		return instance;
	}
	
	private TimeGraphMouseHandler() {
		
	}
	@Override
	public void mouseClicked(MouseEvent e) {
		TimeGraph.getInstance().setVisible(false,null);
		Pad pad=Pad.getInstance();
		Coordinate c = pad.getPosition(e.getPoint());
		TimeGraph.getInstance().setVisible(true,c);
	}

	@Override
	public void mouseEntered(MouseEvent e) {
	}

	@Override
	public void mouseExited(MouseEvent e) {
	}

	@Override
	public void mousePressed(MouseEvent e) {
	}

	@Override
	public void mouseReleased(MouseEvent e) {
	}
	
}