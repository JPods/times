package com.instinct.gui.pad;

import java.awt.Point;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.awt.event.MouseMotionListener;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseWheelListener;

import com.instinct.gui.TimeGraph;

public class DefaultMapController implements MouseListener, MouseMotionListener, MouseWheelListener {
	private Pad map;

	public DefaultMapController(Pad map) {
		this.map = map;
	}

	private Point lastDragPoint;

	public void mouseDragged(MouseEvent e) {
		mouseDragged(e.getPoint());
	}

	public void mouseClicked(MouseEvent e) {
		if (e.getClickCount() == 2 && e.getButton() == MouseEvent.BUTTON1) {
			if (map.getZoom() >= 14) {
				return;
			}
			map.zoomIn(e.getPoint());
		}
	}

	public void mousePressed(MouseEvent e) {
	}

	public void mouseReleased(MouseEvent e) {
		lastDragPoint = null;
	}

	public void mouseWheelMoved(MouseWheelEvent e) {
		if (TimeGraph.getInstance().isVisible()) {
			return;
		}
		if (map.getZoom() < 9) {
			return;
		}
		//map.setZoom(e.getWheelRotation(), e.getPoint());
	}

	private void mouseDragged(Point p) {
		if (lastDragPoint != null) {
			int diffx = lastDragPoint.x - p.x;
			int diffy = lastDragPoint.y - p.y;
			map.moveMap(diffx, diffy);
		}
		lastDragPoint = p;
	}

	public void mouseEntered(MouseEvent e) {
	}

	public void mouseExited(MouseEvent e) {
	}

	@Override
	public void mouseMoved(MouseEvent arg0) {

	}

}