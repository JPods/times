package com.instinct.objects.network;

import java.awt.Point;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.geom.Point2D;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import javax.swing.JMenuItem;
import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.config.Config;
import com.instinct.gui.pad.GeocodeUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.CurveUI;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.objects.pod.Pod;
import com.instinct.objects.simulation.event.TickEvent;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.WorkspaceManager;

public class Line implements RenderableObject<Line>, PodQueueHolder, Serializable, Comparable {

	private static final long serialVersionUID = 1L;

	private String id;
	private double length;
	private Node start, end;
	private PodQueue queue =new PodQueue(100);
	private CurveUI ui;
	private List<Coordinate> coordinates = new ArrayList<Coordinate>();
	private Coordinate dragPoint;
	private List<Point> points = new ArrayList<Point>();
	
	private String trafficCircleId;
	
	private static AtomicInteger idGen=new AtomicInteger(0);

	private double pixelLength;

	private boolean isNetworkElement=true;

	private float angle;

	private JPopupMenu popup;

	public Line(Node start) {
		id="L"+idGen.getAndIncrement();
		this.start = start;
		ui = new CurveUI(this);
		buildMenu();

	}
	
	
	
	public String getTrafficCircleId() {
		return trafficCircleId;
	}
	
	public boolean isPartOfTrafficCircle() {
		if(trafficCircleId!=null && trafficCircleId.trim().length()>0) {
			return true;
		}
		return false;
	}



	public void setTrafficCircleId(String trafficCircleId) {
		this.trafficCircleId = trafficCircleId;
	}



	public static int getLastId() {
		return idGen.get();
	}

	public Line(String id, Node start, Node end, List<Coordinate> cs) {
		this.id=id;
		ui = new CurveUI(this);
		this.start=start;
		this.end=end;
		coordinates.addAll(cs);
		recomputeLength();
		buildMenu();
	}

	public Drawable<Line> getUI() {
		return ui;
	}

	private void computeAngle() {
		Point start=Pad.getInstance().getMapPosition(getStart().getLat(), getStart().getLon(), false);
		Point end=Pad.getInstance().getMapPosition(getEnd().getLat(), getEnd().getLon(), false);
	    float angle = (float) Math.toDegrees(Math.atan2(end.getY() - start.getY(), end.getX() - start.getX()));
	    this.angle=angle;
	}
	
	public float getAngle() {
		return angle;
	}
	
	
	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((id == null) ? 0 : id.hashCode());
		return result;
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (getClass() != obj.getClass())
			return false;
		Line other = (Line) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}

	public void recomputeLength() {
		createCoordinates();
		this.length = computeGeoLength();
		creatPoints();
		this.pixelLength = computePixelLength();
		computeAngle();
		queue.setTimeStayed((int)length);
	}

	private void creatPoints() {
		points.clear();
		for (Coordinate c : coordinates) {
			Point p = Pad.getInstance().getMapPosition(c, false);
			points.add(p);
		}

	}
	
	public double computeLineGap() {
		Pod tailPod=getPodQueue().getTailPod();
		if(tailPod!=null) {
			return tailPod.getDistanceSinceLastNode();
		} else {
			return getLength();
		}
	}

	public void drag(Point p) {
		Coordinate c = Pad.getInstance().getPosition(p);
		if (c != null) {
			dragPoint = c;
			recomputeLength();
		}
	}

	private double computePixelLength() {
		double length = 0;
		for (int i = 0; i < points.size() - 1; i++) {
			Point2D p0 = points.get(i);
			Point2D p1 = points.get(i + 1);
			length += p0.distance(p1);
		}
		return length;
	}

	public Point2D getMidPoint(Coordinate p1, Coordinate p2) {
		return new Point2D.Double((p2.getLon() + p1.getLon()) / 2, (p2.getLat() + p1.getLat()) / 2);
	}

	private void createCoordinates() {
		if(start==null) {
			System.out.println("Start Null for Line "+id);
		}
		if(end==null) {
			System.out.println("End Null for Line "+id);
		}
		Coordinate c1 = new Coordinate(start.getLat(), start.getLon());
		Coordinate c2 = new Coordinate(end.getLat(), end.getLon());
		coordinates.clear();
		coordinates.add(c1);
		if (dragPoint != null) {
			coordinates.add(dragPoint);
		}
		coordinates.add(c2);
	}

	public List<Coordinate> getCoordinates() {
		return coordinates;
	}

	public void setCoordinates(List<Coordinate> coordinates) {
		this.coordinates = coordinates;
	}

	private double computeGeoLength() {
		double straightDistanceGeo = GeocodeUtil.distVincenty(start.getLat(), start.getLon(), end.getLat(), end.getLon());
		return straightDistanceGeo;
	}

	private Point2D computePointAt(double length) {
		if (length < 0) {
			Point2D p = points.get(0);
			return new Point2D.Double(p.getX(), p.getY());
		}
		if (length > pixelLength) {
			Point2D p = points.get(points.size() - 1);
			return new Point2D.Double(p.getX(), p.getY());
		}
		double currentLength = 0;
		for (int i = 0; i < points.size() - 1; i++) {
			Point2D p0 = points.get(i);
			Point2D p1 = points.get(i + 1);
			double distance = p0.distance(p1);
			double nextLength = currentLength + distance;
			if (nextLength > length) {
				double rel = 1 - (nextLength - length) / distance;
				double x0 = p0.getX();
				double y0 = p0.getY();
				double dx = p1.getX() - p0.getX();
				double dy = p1.getY() - p0.getY();
				double x = x0 + rel * dx;
				double y = y0 + rel * dy;
				return new Point2D.Double(x, y);
			}
			currentLength = nextLength;
		}
		Point2D p = points.get(points.size() - 1);
		return new Point2D.Double(p.getX(), p.getY());
	}

	public void setStart(Node node) {
		this.start = node;
		recomputeLength();
	}

	public PodQueue getPodQueue() {
		return queue;
	}

	@Override
	public String toString() {
		return id;
	}

	public double getFrontGapAfterUnitTime() {
		double gap = 0;
		if (queue.getTotalNosOfPods() == 0) {
			gap = length;
		} else {
			Pod frontPod = queue.getHeadPod();
			gap = length - frontPod.getDistanceSinceLastNode() - frontPod.getVelocity();
		}
		return gap;
	}

	public boolean isBetween(Node start, Node end) {
		if (this.start.getId().equals(start.getId()) && this.end.getId().equals(end.getId())) {
			return true;
		}
		return false;
	}

	public double getTailGap() {
		double gap = 0;
		if (queue.getTotalNosOfPods() == 0) {
			gap = length;
		} else {
			Pod tailPod = queue.getTailPod();
			if(tailPod!=null) {
				gap = tailPod.getDistanceSinceLastNode();
			} else {
				gap=length;
			}
		}
		return gap;
	}

	public String getId() {
		return id;
	}

	public double getLength() {
		return length;
	}

	public Node getStart() {
		return start;
	}

	public Node getEnd() {
		return end;
	}

	public void setEnd(Node endNode) {
		this.end = endNode;
		recomputeLength();
	}
	
	
	public Point2D getPointAt(Pad pad, double span) {
		if (span > length) {
			return null;
		}
		Point startP = pad.getMapPosition(start.getLat(), start.getLon(), false);
		Point endP = pad.getMapPosition(end.getLat(), end.getLon(), false);
		if (startP == null | endP == null) {
			return null;
		}
		double pixelSpan = span * (pixelLength / length);
		return computePointAt(pixelSpan);
	}

	public Coordinate getCoordinateAt(Pad pad, double span) {
		Point2D p=getPointAt(pad, span);
		if(p!=null) {
			return pad.getPosition((int)p.getX(),(int)p.getY());
		}
		return null;
	}
	
	
	public void remove() {
		if(start!=null && start instanceof Switch) {
			((Switch)start).detachExitLine(this);
		}
		if(end!=null && end instanceof Switch) {
			((Switch) end).detachEntryLine(this);
		}
		
		if(isNetworkElement) {
		WorkspaceManager.getInstance().getNetwork().removeLine(this);
		} else {
			WorkspaceManager.getInstance().getNetwork().removeBoundaryLine(this);
			
		}

	}
	
	public void removeWithinNodeGroup() {
		if(start instanceof Switch) {	
			((Switch) start).detachExitLine(this);
		} else {
			((Station) start).setExit(null);

		}
		
		if(end instanceof Switch) {
			((Switch) end).detachEntryLine(this);
		} else {
			((Station) end).setEntry(null);

		}
		WorkspaceManager.getInstance().getNetwork().removeLine(this);

	}


	public static void setLastId(int lastId) {
		idGen.set(lastId+1);
		
	}
	
	@Override
	public int compareTo(Object obj) {
		int id1=Integer.parseInt(this.id.replace("L", ""));
		int id2=Integer.parseInt(this.id.replace("L", ""));
		return id1-id2;
	}

	public void propagateEvent() {
		List<Pod> pods=this.getPodQueue().getAll();
		for(int i=0;i<pods.size();i++) {
			Pod pod=pods.get(i);
			pod.sendEvent(GlobalTimeKeeper.getInstance().getTime(),new TickEvent());
		}
	}


	public double getHeadGap() {
		if(getPodQueue().size()==0) {
			return getLength();
		} else {
			Pod headPod=getPodQueue().getHeadPod();
			return getLength()-headPod.getDistanceSinceLastNode();
		}
	}


	public boolean isConverging() {
		if (!(getEnd() instanceof Switch)) {
			return false;
		}
		Switch sw = (Switch) getEnd();
		return sw.getEntryCount() == 2;
	}
	
	public boolean isDiverging() {
		if (!(getEnd() instanceof Switch)) {
			return false;
		}
		Switch sw = (Switch) getEnd();
		return sw.getExitCount() == 2;
	}
	
	
	public double getWeight() {
		if(isJammed()) {
			return Double.MAX_VALUE;
		} else {
			return getLength();
		}
	}

	public double computeAvgSpeed() {
		double totalVelocity=0;
		int count=0;
		for(int i=0;i<getPodQueue().size()-1;i++) {
			totalVelocity+=getPodQueue().getPodByPos(i).getVelocity();
			count++;
		}
		double avgVelocity=totalVelocity/count;
		return avgVelocity;
	}
	
	public boolean isJammed() {
		if(this.getPodQueue().size()<4) {
			return false;
		}
		//TODO has to be logarithmic
		double metersPerPod=length/this.getPodQueue().size();
		if(metersPerPod>8) {
			return false;
		}
		return true;
	}

	public boolean isNetworkElement() {
		return isNetworkElement;
	}
	
	public void setNetworkElement(boolean isNetworkLine) {
		this.isNetworkElement=isNetworkLine;
	}

	private void buildMenu() {
		popup = new JPopupMenu();
		final Line self=this;
		ActionListener aListener=new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				if(ae.getActionCommand().equals("Delete")) {
					self.remove();
					Pad.getInstance().updateUI();
					NetworkTree.getInstance().updateTree();
				}
			}
			
		};
		JMenuItem item;
	    popup.add(item = new JMenuItem("Delete"));
	    item.addActionListener(aListener);

	}

	@Override
	public JPopupMenu getPopupMenu() {
		return popup;
	}

}
