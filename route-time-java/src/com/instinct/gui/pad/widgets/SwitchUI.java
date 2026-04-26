package com.instinct.gui.pad.widgets;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Point2D;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Switch;
import com.instinct.service.SimulationManager;

public class SwitchUI extends Ellipse2D.Double implements Drawable<Switch> {
	private boolean isHighlight;
	private Switch model;
	private boolean isGlow;
	private boolean isGrouped;

	public SwitchUI(Point2D p, Switch model) {
		super(p.getX(), p.getY() - 6, 10, 10);
		this.model = model;
	}

	@Override
	public boolean contains(Point p) {
		if (p == null) {
			return false;
		}
		return super.contains(p);
	}

	@Override
	public void draw(Graphics2D g2, Pad pad) {
		Point2D p = GUIUtil.getMapPoint(pad, model);
		if (p == null) {
			return;
		}

		if (model.isNetworkElement() == false) {
			drawForFenceCorner(g2, pad, p);
			return;
		}


		if (isGlow) {
			drawGlow(g2, pad, p);
		}


		if (isInvalid()) {
			highlightValidation(g2, pad, p);
		}

		if (Pad.getInstance().getZoom() > 15 && SimulationManager.getInstance().isSimulationRunning()==false) {
			this.setFrame(p.getX() - 6, p.getY() - 6, 10, 10);
		} else {
			this.setFrame(p.getX() - 3, p.getY() - 3, 5, 5);
		}
		g2.draw(this);
		if (model.getEntryCount() == 2) {
			g2.setColor(Color.CYAN);
		} else if (model.getExitCount() == 2) {
			g2.setColor(Color.MAGENTA);
		} else {
			g2.setColor(Color.BLACK);
		}
		g2.fill(this);
		g2.setColor(Color.BLACK);
		if (Pad.getInstance().getZoom() > 15) {
			g2.setFont(new Font("default", Font.BOLD, 10));
			g2.drawString(model.toString(), (int) p.getX(), (int) p.getY() - 20);
		}

		drawGroup(g2, pad, p);

		if (isHighlight) {
			highlight(g2, pad, p);
		}
}

	private void drawForFenceCorner(Graphics2D g2, Pad pad, Point2D p) {
		this.setFrame(p.getX() - 4, p.getY() - 4, 8, 8);
		g2.draw(this);
		g2.setColor(Color.YELLOW);
		g2.fill(this);
		g2.setColor(Color.black);
		if (isGlow) {
			drawGlow(g2, pad, p);
		}
		drawGroup(g2, pad, p);
	}

	private void drawGlow(Graphics2D g2, Pad pad, Point2D p) {
		Ellipse2D.Double e = new Ellipse2D.Double();
		if (Pad.getInstance().getZoom() > 15) {
			e.setFrame(p.getX() - 30, p.getY() - 30, 60, 60);
		} else {
			e.setFrame(p.getX() - 6, p.getY() - 6, 24, 24);
		}
		Color oldColor = g2.getColor();
		g2.setColor(Color.YELLOW);
		g2.fill(e);
		g2.setColor(oldColor);

	}

	private void drawGroup(Graphics2D g2, Pad pad, Point2D p) {
		if(isGrouped==false) {
			return;
		}
		g2.setColor(Color.GREEN);
		int x = (int) p.getX() - 5;
		int y = (int) p.getY() - 5;
		Rectangle r = getBounds();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);
	}

	private boolean isInvalid() {
		return model.getExitCount() == 0 || model.getEntryCount() == 0 || (model.getEntryCount() == 2 && model.getExitCount() == 2);
	}

	private void highlight(Graphics2D g2, Pad pad, Point2D p) {
		g2.setColor(Color.GREEN);
		int x = (int) p.getX() - 5;
		int y = (int) p.getY() - 5;
		Rectangle r = getBounds();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);
		g2.setColor(Color.BLACK);

	}

	private void highlightValidation(Graphics2D g2, Pad pad, Point2D p) {
		g2.setColor(Color.RED);
		int x = (int) p.getX() - 5;
		int y = (int) p.getY() - 5;
		Rectangle r = getBounds();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

	}

	@Override
	public String getId() {
		return model.getId();
	}

	@Override
	public void setHighlight(boolean isHighLight) {
		if (this.isHighlight == isHighLight) {
			return;
		}
		this.isHighlight = isHighLight;
		if (model.isNodeGroup()) {
			model.getNodeGroup().setHighlight(isHighLight);
		}
	}

	@Override
	public void showEditor() {
	}

	@Override
	public Switch getModel() {
		return model;
	}

	@Override
	public double distance(Point p) {
		Coordinate p1 = Pad.getInstance().getPosition(p);
		return GeocodeUtil.distVincenty(p1.getLat(), p1.getLon(), model.getLat(), model.getLon());
	}

	@Override
	public void setGlow(boolean isGlow) {
		this.isGlow = isGlow;
	}

	@Override
	public void setGrouped(boolean isGrouped) {
		this.isGrouped = isGrouped;
	}
}
