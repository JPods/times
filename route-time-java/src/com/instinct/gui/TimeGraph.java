package com.instinct.gui;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Paint;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.Stroke;
import java.awt.geom.Area;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Line2D;
import java.awt.geom.RoundRectangle2D;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.config.Config;
import com.instinct.config.TimeColor;
import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Station;
import com.instinct.service.WorkspaceManager;

public class TimeGraph {

	private boolean isVisible = false;
	private Coordinate c;

	private static TimeGraph instance = new TimeGraph();

	public static TimeGraph getInstance() {
		return instance;
	}

	private TimeGraph() {

	}

	public boolean isVisible() {
		return isVisible;
	}

	public void drawGraph(Graphics2D g) {
		if (!isVisible) {
			return;
		}
		GraphPainter painter = new GraphPainter(c, g);
		painter.compute();
	}

	public void setVisible(boolean b, Coordinate c) {
		this.c = c;
		this.isVisible=b;
		Pad.getInstance().updateUI();
	}
}

class GraphPainter {
	private Coordinate c;
	private Graphics2D g;
	private Map<Integer, Area> circles = new HashMap<Integer, Area>();

	public GraphPainter(Coordinate c, Graphics2D g) {
		this.c = c;
		this.g = g;
	}

	public void compute() {

		createPointCircle(30);
		createPointCircle(20);
		createPointCircle(10);
		createPointCircle(5);
		
		
		Station start = choseStation(c);
		int walkingTimeToNearestStation = getWalkingTimeInMinutes(c, start);
		drawTier(start, 30, walkingTimeToNearestStation);
		drawTier(start, 20, walkingTimeToNearestStation);
		drawTier(start, 10, walkingTimeToNearestStation);
		drawTier(start, 5, walkingTimeToNearestStation);
		
		drawCross();
		drawLegend();

	}

	private void drawCross() {
		Point p = Pad.getInstance().getMapPosition(c, false);

		double radius=3;
		double lineLength=30;
		Ellipse2D theCross = new Ellipse2D.Double(p.getX() - radius, p.getY() - radius, 2.0 * radius, 2.0 * radius);
		
		Color oldColor=g.getColor();
		Stroke oldStroke=g.getStroke();
		g.setColor(Color.decode("#F50057"));
		g.draw(theCross);
		g.fill(theCross);
		g.setStroke(new BasicStroke(4f));
		Line2D lineUp = new Line2D.Double(p.getX(), p.getY(),p.getX(),p.getY()-lineLength);
		g.draw(lineUp);
		g.fill(lineUp);
		Line2D lineDown = new Line2D.Double(p.getX(), p.getY(),p.getX(),p.getY()+lineLength);
		g.draw(lineDown);
		g.fill(lineDown);
		Line2D lineEast = new Line2D.Double(p.getX()+lineLength, p.getY(),p.getX(),p.getY());
		g.draw(lineEast);
		g.fill(lineEast);
		Line2D lineWest = new Line2D.Double(p.getX()-lineLength, p.getY(),p.getX(),p.getY());
		g.draw(lineWest);
		g.fill(lineWest);
		g.setColor(oldColor);
		g.setStroke(oldStroke);
	}

	private void drawLegend() {
		
		Rectangle r=g.getClipBounds();
		
		Stroke oldStroke=g.getStroke();
		Color oldColor=g.getColor();
		
		
		g.setStroke(new BasicStroke(4f));
		g.setFont(new Font("default", Font.BOLD, 17));

		RoundRectangle2D container=new RoundRectangle2D.Double(r.x+r.width-210, r.y+r.height-270, 200, 160, 10, 10);
        g.setColor(Color.white);
        g.fill(container);
        
		RoundRectangle2D rounded5Min = new RoundRectangle2D.Double(r.x+r.width-200, r.y+r.height-260, 25, 25, 5, 5);
        g.setColor(TimeColor.getMetalicColorByMinute(5));
        g.fill(rounded5Min);
        g.setColor(oldColor);
		g.drawString("5 Min", r.x+r.width-160, r.y+r.height-240);
        
		RoundRectangle2D rounded10Min = new RoundRectangle2D.Double(r.x+r.width-200, r.y+r.height-220, 25, 25, 5, 5);
        g.setColor(TimeColor.getMetalicColorByMinute(10));
        g.fill(rounded10Min);
        g.setColor(oldColor);
        g.drawString("10 Min", r.x+r.width-160, r.y+r.height-200);
		
        RoundRectangle2D rounded20Min = new RoundRectangle2D.Double(r.x+r.width-200, r.y+r.height-180, 25, 25, 5, 5);
        g.setColor(TimeColor.getMetalicColorByMinute(20));
        g.fill(rounded20Min);
        g.setColor(oldColor);
        g.drawString("20 Min", r.x+r.width-160, r.y+r.height-160);
		
        RoundRectangle2D rounded30Min = new RoundRectangle2D.Double(r.x+r.width-200, r.y+r.height-140, 25, 25, 5, 5);
        g.setColor(TimeColor.getMetalicColorByMinute(30));
        g.fill(rounded30Min);
        g.setColor(oldColor);
        g.drawString("30 Min", r.x+r.width-160, r.y+r.height-120);

        

		g.setStroke(oldStroke);
		g.setColor(oldColor);
	}

	private void createPointCircle(int circleTime) {
		double d = Config.getInstance().getWalkingDistanceInMinsInMeters(circleTime);
		double meterPerPixel = Pad.getInstance().getMeterPerPixel();
		double radius = d / meterPerPixel;
		if (radius <= 1) {
			return;
		}

		Point p = Pad.getInstance().getMapPosition(c, false);

		Ellipse2D theCircle = new Ellipse2D.Double(p.getX() - radius, p.getY() - radius, 2.0 * radius, 2.0 * radius);
		if (!circles.containsKey(circleTime)) {
			circles.put(circleTime, new Area(theCircle));
		} else {
			circles.get(circleTime).add(new Area(theCircle));
		}		
	}

	private void drawTier(Station closestStation, int circleTime, int walkingTimeToNearestStation) {
		for (Station st : WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			if (st.equals(closestStation) && walkingTimeToNearestStation <= circleTime) {
				createCircle(walkingTimeToNearestStation,0, circleTime, st);
			} else {
				int resolution=(WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec());
				int travelTimeToThisStation = (int) WorkspaceManager.getInstance().getWorkingSim().getAvgTime(closestStation, st) /(resolution*60);
				if(travelTimeToThisStation>0) {
					createCircle(walkingTimeToNearestStation,travelTimeToThisStation, circleTime, st);
				}
			}
		}
		drawCircles(circleTime);
	}




	private void createCircle(int walkingTimeToNearestStation, int travelTimeToThisStation, int circleTime, Station st) {
		if((walkingTimeToNearestStation+travelTimeToThisStation)>circleTime) {
			return;
		}
		
		double d = Config.getInstance().getWalkingDistanceInMinsInMeters(circleTime-travelTimeToThisStation-walkingTimeToNearestStation);
		double meterPerPixel = Pad.getInstance().getMeterPerPixel();
		double radius = d / meterPerPixel;
		if (radius <= 1) {
			return;
		}

		Point p = Pad.getInstance().getMapPosition(st.getLat(), st.getLon(), false);

		Ellipse2D theCircle = new Ellipse2D.Double(p.getX() - radius, p.getY() - radius, 2.0 * radius, 2.0 * radius);
		if (!circles.containsKey(circleTime)) {
			circles.put(circleTime, new Area(theCircle));
		} else {
			circles.get(circleTime).add(new Area(theCircle));
		}

	}

	private int getWalkingTimeInMinutes(Coordinate p, Station start) {
		double d = GeocodeUtil.distVincenty(p, new Coordinate(start.getLat(), start.getLon()));
		double t = d / (Config.getInstance().getWalkingSpeedKMPH() * 1000 / 60);
		return (int) t;
	}
	
	private void drawCircles(int i) {
		if (!circles.containsKey(i)) {
			return;
		}
		
		Area shape = circles.get(i);
		Color c = TimeColor.getMetalicColorByMinute(i);
		Paint oldPaint = g.getPaint();
		Stroke oldStroke=g.getStroke();
		g.setStroke(new BasicStroke(6.0f));
	    g.setPaint(c);
		g.draw(shape);
		g.setPaint(oldPaint);
		g.setStroke(oldStroke);
	}
	
	
	private Station choseStation(Coordinate c) {
		Collection<Station> list = WorkspaceManager.getInstance().getNetwork().getAllStations();
		double lowest = Double.MAX_VALUE;
		Station ret = null;
		for (Station st : list) {
			double distance = GeocodeUtil.distVincenty(new Coordinate(st.getLat(), st.getLon()), c);
			if (lowest > distance) {
				lowest = distance;
				ret = st;
			}
		}
		return ret;
	}
}
