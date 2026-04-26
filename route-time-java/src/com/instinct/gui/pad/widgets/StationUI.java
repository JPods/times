package com.instinct.gui.pad.widgets;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.Stroke;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Point2D;
import java.awt.geom.Rectangle2D;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.property.CompositePropertyEditor;
import com.instinct.gui.property.FormBuilder;
import com.instinct.objects.network.Station;

public class StationUI extends Rectangle2D.Double implements Drawable<Station> {
	private boolean isHighlight;
	private Station model;
	private boolean isGlow;
	private boolean isGrouped;

	public StationUI(Point2D p, Station model) {
		super(p.getX() - 5, p.getY() - 5, 10, 10);
		this.model = model;
	}

	@Override
	public void showEditor() {
		CompositePropertyEditor stationProperty = FormBuilder.getInstance().makeStationProperty(model);
		stationProperty.setVisible(true);
	}

	@Override
	public String getId() {
		return model.getId();
	}

	private void highlight(Graphics2D g2, Pad pad) {
		g2.setColor(Color.GREEN);
		Rectangle r = getBounds();
		int x = (int) r.getX();
		int y = (int) r.getY();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

	}

	@Override
	public boolean contains(Point p) {
		return super.getFrame().contains(p);
	}

	@Override
	public void draw(Graphics2D g2, Pad pad) {
		Point2D p = GUIUtil.getMapPoint(pad, model);
		if (p == null) {
			return;
		}

		this.setFrame(p.getX() - 5, p.getY() - 5, 10, 10);
		g2.setColor(Color.black);
		g2.draw(this);
		if(Pad.getInstance().getZoom()>17) {
			putLabel(g2, p);
		}
		if (isHighlight) {
			highlight(g2, pad);
		}

		if(isGlow) {
			drawGlow(g2, pad,p);
		}
		
		if(isGrouped)  {
			drawGroup(g2, pad);
		}
	}	

	private void drawGroup(Graphics2D g2, Pad pad) {
		Color oldColor=g2.getColor();
		g2.setColor(Color.GREEN);
		Rectangle r = getBounds();
		int x = (int) r.getX();
		int y = (int) r.getY();
		int width = (int) r.getWidth()+2;
		int height = (int) r.getHeight()+2;
		
		Stroke oldStroke=g2.getStroke();
		g2.setStroke(new BasicStroke(2));
		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

		g2.setColor(oldColor);
		g2.setStroke(oldStroke);
	}
	
	private void drawGlow(Graphics2D g2, Pad pad, Point2D p) {
		Ellipse2D.Double e=new Ellipse2D.Double();
		if(Pad.getInstance().getZoom()>15) {
			e.setFrame(p.getX()-15,p.getY()-15, 30, 30);
		} else {
			e.setFrame(p.getX()-3,p.getY()-3, 12, 12);
		}
		Color oldColor=g2.getColor();
		 g2.setColor(Color.YELLOW);
		 g2.fill(e);
		 g2.setColor(oldColor);
		
	}



	private void putLabel(Graphics2D g2, Point2D p) {
		StringBuilder sb = new StringBuilder();
		sb.append(model);
		sb.append("(");
		sb.append(model.getPassengerQueue().size());
		sb.append("/");
		sb.append(model.getPodQueue().size());
		sb.append(")");
		g2.setColor(Color.BLACK);
		g2.setFont(new Font("default", Font.BOLD, 12));
		g2.drawString(sb.toString(), (int) p.getX(), (int) p.getY() - 40);
	}
	

	@Override
	public void setHighlight(boolean isHighLight) {
		if(this.isHighlight==isHighLight) {
			return; //Break recurssion;
		}
		this.isHighlight = isHighLight;
		if(model.isNodeGroup()) {
			model.getNodeGroup().setHighlight(isHighLight);
		}
	}

	@Override
	public Station getModel() {
		return model;
	}

	@Override
	public double distance(Point p) {
		Coordinate p1=Pad.getInstance().getPosition(p);
		return GeocodeUtil.distVincenty(p1.getLat(), p1.getLon(), model.getLat(), model.getLon());
	}

	@Override
	public void setGlow(boolean isGlow) {
		this.isGlow=isGlow;
	}

	@Override
	public void setGrouped(boolean isGrouped) {
		this.isGrouped=isGrouped;
	}	

}
