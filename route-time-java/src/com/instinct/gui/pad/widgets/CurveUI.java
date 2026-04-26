package com.instinct.gui.pad.widgets;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.geom.Line2D;
import java.awt.geom.Point2D;
import java.util.ArrayList;
import java.util.List;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.property.CompositePropertyEditor;
import com.instinct.gui.property.FormBuilder;
import com.instinct.objects.network.Line;
import com.instinct.service.SimulationManager;

public class CurveUI implements Drawable<Line> {

	private Line line;
	private boolean isHighlighted = false;
	private List<Line2D> lines = new ArrayList<Line2D>();
	private boolean isGrouped;

	public CurveUI(Line modelLine) {
		this.line = modelLine;
	}

	public void setHighlight(boolean isHighlighted) {
		this.isHighlighted = isHighlighted;
	}

	@Override
	public void showEditor() {
		CompositePropertyEditor lineProperty = FormBuilder.getInstance().makeLineProperty(line);
		lineProperty.setVisible(true);
	}

	public void setModel(Line modelLine) {
		this.line = modelLine;
	}

	public void draw(Graphics2D g2, Pad pad) {

		if (line.getEnd() == null) {
			return;
		}
		    
		Color oldColor = g2.getColor();
		if(line.isNetworkElement()==false) {
			g2.setColor(Color.BLUE);
		} else if(line.isJammed() && SimulationManager.getInstance().isSimulationRunning()) {
			g2.setColor(Color.RED);
		} else {
			setColor(g2);
		}
		computeLines();
		drawCurve(g2);
		if (lines.size() > 0) {
			Line2D lastLine = lines.get(lines.size() - 1);
			g2.setFont(new Font("default", Font.BOLD, 12));
			if (Pad.getInstance().getZoom() > 16) {
				drawArrow(g2, lastLine.getP1(), lastLine.getP2());
			}
		}

		if(pad.getZoom()>16) {
			addLabel(g2, pad);
		}
		
		
		g2.setColor(oldColor);
	}

	private void addLabel(Graphics2D g2, Pad pad) {
		
		g2.setFont(new Font("default", Font.BOLD, 12));
		
		double midLat=(line.getStart().getLat()+line.getEnd().getLat())/2;
		double midLon=(line.getStart().getLon()+line.getEnd().getLon())/2;
		Point p=pad.getMapPosition(midLat, midLon,false);
		g2.drawString(line.toString(), (int)p.getX(),(int)p.getY());
	}



	private void drawCurve(Graphics2D g) {
		for (Line2D line : lines) {
			g.draw(line);
		}
	}


	private void computeLines() {
		line.recomputeLength();
		lines.clear();
		for (int i = 0; i < line.getCoordinates().size() - 1; i++) {
			Coordinate c1 = line.getCoordinates().get(i);
			Coordinate c2 = line.getCoordinates().get(i + 1);
			Point p1 = Pad.getInstance().getMapPosition(c1, false);
			Point p2 = Pad.getInstance().getMapPosition(c2, false);
			if (p1 != null && p2 != null) {
				Line2D line = new Line2D.Double(p1.getX(), p1.getY(), p2.getX(), p2.getY());
				lines.add(line);
			}
		}
	}

	private void drawArrow(Graphics2D g2, Point2D start, Point2D end) {
		Arrow arrow = new Arrow(Arrow.CLASSIC, 10, 10);
		arrow.drawArrow(g2, (int) start.getX(), (int) start.getY(), (int) end.getX(), (int) end.getY(), 10);
	}

	private void setColor(Graphics2D g2) {
		if (isHighlighted) {
			g2.setColor(Color.GREEN);
		} else if(isInvalid()){
			g2.setColor(Color.RED);
		} else {
			g2.setColor(Color.BLACK);
			
		}
	}

	private boolean isInvalid() {
		return line.getEnd()==null || line.getStart()==null;
	}

	public Line getModel() {
		return line;
	}

	public String toString() {
		return line.toString();
	}

	public String getId() {
		return line.getId();
	}

	@Override
	public boolean contains(Point p) {

		for (Line2D line : lines) {
			if (withinLine(line, p)) {
				return true;
			}
		}
		return false;
	}

	private boolean withinLine(Line2D line, Point p) {
		int allowedDistance = 2;
		Point2D p1 = line.getP1();
		Point2D p2 = line.getP2();
		double c = Math.abs(p1.distance(p2));
		if (c < allowedDistance) {
			return false;
		}

		double a = Math.abs(p.distance(p1));
		double b = Math.abs(p.distance(p2));
		double distance = Math.abs(c - (a + b));
		return allowedDistance > distance;
	}

	@Override
	public double distance(Point p) {
		double lowest=Double.MAX_VALUE;
		for (Line2D line : lines) {
			double d=Math.abs(line.ptLineDist(p));
			if(d<lowest) {
				lowest=d;
			}
		}
		return lowest;
	}

	@Override
	public void setGlow(boolean isGlow) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void setGrouped(boolean isGrouped) {
		this.isGrouped=isGrouped;
		
	}

}