package com.instinct.gui.pad;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Cursor;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.Shape;
import java.awt.Stroke;
import java.awt.event.MouseEvent;
import java.awt.event.MouseMotionListener;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseWheelListener;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Rectangle2D;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Timer;
import java.util.TimerTask;

import javax.swing.BorderFactory;
import javax.swing.ImageIcon;

import org.openstreetmap.gui.jmapviewer.Coordinate;
import org.openstreetmap.gui.jmapviewer.JMapViewer;
import org.openstreetmap.gui.jmapviewer.tilesources.BingAerialTileSource;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.StatusBar;
import com.instinct.gui.TimeGraph;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.pad.widgets.PodUI;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.RenderableObject;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.pod.Pod;
import com.instinct.service.HttpRequestor;
import com.instinct.service.WorkspaceManager;
import com.instinct.service.dijkstra.MergeLoadCalculator;

public class Pad extends JMapViewer {

	private PadController controller = new PadController(this);

	private Drawable currentlyHighlighted = null;

	private ImageIcon logo;

	private static Pad instance = new Pad();

	private Drawable currentlyGlowing = null;

	private ImageIcon cursor;

	private Point cursorPoint;

	private boolean isGroupSelectEnabled;

	private Point topLeftGroupCorner;

	private Point bottomRightGroupCorner;

	private java.awt.geom.Rectangle2D.Double selectRectangle;

	private int scrollAmount;

	private String alertMsg = null;

	private boolean isHandCursor;

	private boolean drawMergeLoad;


	public static Pad getInstance() {
		return instance;
	}
	

	public Pad() {
		setBorder(BorderFactory.createLineBorder(Color.BLACK));
		setTileSource(new BingAerialTileSource());
		this.addMouseListener(controller);
		this.addMouseMotionListener(controller);
		this.setOpaque(false);
		this.setZoom(11);
		logo = GUIUtil.getLogoImage("logo.png");

		this.addMouseMotionListener(new CursorLocationUpdator());

		this.addMouseWheelListener(new MouseWheelListener() {
			@Override
			public void mouseWheelMoved(MouseWheelEvent e) {
				scrollAmount = scrollAmount + e.getScrollAmount();
			}
		});
	}
	
	

	public void showAlert(String msg) {
		this.alertMsg = msg;

		if (msg != null) {
			Timer timer = new Timer();
			timer.schedule(new TimerTask() {
				@Override
				public void run() {
					Pad.getInstance().showAlert(null);

				}
			}, 2000);
		}
	}
	
	public void showAlertIndefinte(String msg) {
		this.alertMsg=msg; 

	}

	@Override
	public void setZoom(int newZoom, Point mapPoint) {
		super.setZoom(newZoom, mapPoint);
		if (scrollAmount > 5) {
			scrollAmount = 0;
		}
	}
	

	public void setCursorImage(String cursorImg) {
		if (cursorImg == null) {
			cursor = null;
			isHandCursor=false;
			return;
		}
		if(cursorImg.equals("hand.png")) {
			isHandCursor=true;
		} else {
			isHandCursor=false;
		}
		cursor = GUIUtil.getImageWithScale(cursorImg, 32, 32);

	}
	
	public void showHandCursor() {
		setCursorImage("hand.png");
	}
	
	public boolean isHandCursor() {
		return isHandCursor;
	}

	private void highlight(Drawable d) {
		if (currentlyHighlighted != null) {
			currentlyHighlighted.setHighlight(false);
		}
		currentlyHighlighted = d;
		if (d != null) {
			d.setHighlight(true);
			NetworkTree.getInstance().setHighlight(d);
		}
	}

	public void zoomToHighlight(Drawable d) {
		Object model = d.getModel();
		if (model instanceof Node) {
			Node node = (Node) model;
			setDisplayPositionByLatLon(node.getLat(), node.getLon(), 17);
		} else if (model instanceof Line) {
			Line line = (Line) model;
			double lat = (line.getStart().getLat() + line.getEnd().getLat()) / 2;
			double lon = (line.getStart().getLon() + line.getEnd().getLon()) / 2;
			setDisplayPositionByLatLon(lat, lon, 17);

		}
	}

	public void setHighlight(Drawable d) {
		highlight(d);
		updateUI();
	}

	public PadController getController() {
		return controller;
	}

	public void paint(Graphics g) {
		
		super.paint(g);
		drawMergeLoad((Graphics2D)g);
		TimeGraph.getInstance().drawGraph((Graphics2D) g);
		Graphics2D g2 = (Graphics2D) g;
		g2.setStroke(new BasicStroke(2));
		g2.setColor(Color.BLACK);
		drawObjects(g2);
		drawLogo(g2);
		if (isGroupSelectEnabled) {
			drawSelectionRectangle(g2);
		}
		drawCursor(g2);
		if (alertMsg != null) {
			drawAlert(g2);
		}
	}

	private void drawMergeLoad(Graphics2D g) {
		if(drawMergeLoad==false || WorkspaceManager.getInstance().getNetwork()==null) {
			return;
		}
		
		for(Switch sw:WorkspaceManager.getInstance().getNetwork().getAllConvergences()) {
			Point c=this.getMapPosition(sw.getLat(), sw.getLon(), false);
			int load=MergeLoadCalculator.getInstance().getLoad(sw.getId());
			Color oldColor=g.getColor();
			g.setColor(Color.red);
			int a=load*10;
			Shape s=new Ellipse2D.Double(c.x-a/2, c.y-a/2,a,a);
			g.draw(s);
			g.fill(s);
			g.setColor(oldColor);
		}
		
	}


	private void drawAlert(Graphics2D g) {
		Stroke oldStroke = g.getStroke();
		Color oldColor = g.getColor();
		g.setStroke(new BasicStroke(4f));
		g.setColor(Color.RED);
		g.setFont(new Font("default", Font.BOLD, 17));
		g.drawString(alertMsg, Pad.getInstance().getWidth()/2-100, 20);

		g.setColor(oldColor);
		g.setStroke(oldStroke);

	}

	private void drawSelectionRectangle(Graphics2D g2) {
		if (bottomRightGroupCorner == null || topLeftGroupCorner == null) {
			return;
		}
		int width = bottomRightGroupCorner.x - topLeftGroupCorner.x;
		int height = bottomRightGroupCorner.y - topLeftGroupCorner.y;
		if (width > 0 && height > 0) {
			this.selectRectangle = new Rectangle2D.Double(topLeftGroupCorner.x, topLeftGroupCorner.y, width, height);
			g2.draw(selectRectangle);
		}

	}

	public boolean isWithinSelectedRectangle(Point p) {
		if (selectRectangle == null || p == null) {
			return false;
		}

		return selectRectangle.contains(p);
	}

	private void drawCursor(Graphics g) {
		if (cursor != null && cursorPoint != null) {
			g.drawImage(cursor.getImage(), cursorPoint.x + 3, cursorPoint.y + 5, null);
		}

	}

	private void drawLogo(Graphics2D g) {
		Rectangle r = g.getClipBounds();
		if(r==null || logo==null) {
			return;
		}
		g.drawImage(logo.getImage(), r.width - 200, r.y + r.height - 80, null);
	}

	private void drawObjects(Graphics2D g2) {
		if (WorkspaceManager.getInstance().getNetwork() == null) {
			return;
		}
		drawNodes(g2);
		drawLines(g2);
		drawBoundaryNodes(g2);
		drawBoundaryLines(g2);
		drawPods(g2);
		
	}

	private void drawNodes(Graphics2D g2) {
		for (Drawable s : getAllNodeShapes()) {
			s.draw(g2, this);
		}
	}
	
	private void drawBoundaryNodes(Graphics2D g2) {
		for (Drawable s : getAllBoderNodeShapes()) {
			s.draw(g2, this);
		}
	}

	private void drawLines(Graphics2D g2) {
		for (Line l : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			l.getUI().draw(g2, this);
		}

	}

	private void drawBoundaryLines(Graphics2D g2) {
		for (Line l : WorkspaceManager.getInstance().getNetwork().getAllBorderLines()) {
			l.getUI().draw(g2, this);
		}

	}

	private void drawPods(Graphics2D g2) {
		for (Line l : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			List<Pod> pods = new ArrayList<Pod>(l.getPodQueue().getAll());
			for (Pod pod : pods) {
				PodUI podUi = new PodUI(pod);
				podUi.draw(this, g2);
			}
		}

	}

	private Collection<Drawable> getAllNodeShapes() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		if (WorkspaceManager.getInstance().getNetwork() == null) {
			return nodes;
		}
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			if (node instanceof RenderableObject) {
				nodes.add(((RenderableObject) node).getUI());
			}
		}
		return nodes;
	}

	private Collection<Drawable> getAllShapes() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		if (WorkspaceManager.getInstance().getNetwork() == null) {
			return nodes;
		}
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			if (node instanceof RenderableObject) {
				nodes.add(((RenderableObject) node).getUI());
			}
		}

		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			if (line instanceof RenderableObject) {
				nodes.add(((RenderableObject) line).getUI());
			}
		}

		return nodes;
	}

	
	
	private Collection<Drawable> getAllBoderNodeShapes() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		if (WorkspaceManager.getInstance().getNetwork() == null) {
			return nodes;
		}
		for (Node node : WorkspaceManager.getInstance().getNetwork().getAllBoderNodes()) {
			if (node instanceof RenderableObject) {
				nodes.add(((RenderableObject) node).getUI());
			}
		}
		return nodes;
	}

	
	private Collection<Drawable> getAllLines() {
		List<Drawable> nodes = new ArrayList<Drawable>();
		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			if (line instanceof RenderableObject) {
				nodes.add(((RenderableObject) line).getUI());
			}
		}
		return nodes;
	}

	public Drawable<?> getClosestLine(Point p, int allowed) {
		double leastDistance = Double.MAX_VALUE;
		Drawable<?> closest = null;
		for (Drawable<?> s : getAllLines()) {
			double d = Math.abs(s.distance(p));
			if (d < leastDistance && isWithinLineBoundary((Line) s.getModel(), p)) {
				leastDistance = d;
				closest = s;
			}
		}
		if (leastDistance > allowed) {
			return null;
		}
		return closest;
	}

	private boolean isWithinLineBoundary(Line line, Point p) {
		double latH = Math.max(line.getStart().getLat(), line.getEnd().getLat());
		double latL = Math.min(line.getStart().getLat(), line.getEnd().getLat());
		double lonH = Math.max(line.getStart().getLon(), line.getEnd().getLon());
		double lonL = Math.min(line.getStart().getLon(), line.getEnd().getLon());

		Coordinate c = getPosition(p);
		if (latH >= c.getLat() && latL <= c.getLat() && lonH >= c.getLon() && lonL <= c.getLon()) {
			return true;
		}
		return false;
	}

	public Drawable<?> getHighligtableAt(Point p) {

		for (Drawable<?> s : getAllShapes()) {
			if (s.contains(p)) {
				return s;
			}
		}
		return null;
	}
	
	public Drawable<?> getLineAt(Point p) {

		for (Drawable<?> s : getAllLines()) {
			if (s.contains(p)) {
				return s;
			}
		}
		return null;
	}

	public Drawable<? extends Node> getNodeAt(Point p) {
		Network net=WorkspaceManager.getInstance().getNetwork();
		if(net==null) {
			return null;
		}
		Collection<Node> ns=new ArrayList<Node>();
		ns.addAll(net.getAllBoderNodes());
		ns.addAll(net.getAllNodes());
		for (Node s : ns) {
			Drawable d=getDrawable(s);
			if (d.contains(p)) {
				return d;
			}
		}
		return null;
	}

	public void setGlowNetworked(Node node, Point p) {
		if (currentlyGlowing != null) {
			currentlyGlowing.setGlow(false);
		}
		Network net=WorkspaceManager.getInstance().getNetwork();
		if(net==null) {
			return;
		}
		Collection<Node> ns=new ArrayList<Node>();
		ns.addAll(net.getAllNodes());
		setGlow(node, p, ns);
	}

	public void setGlowNonNetworked(Node node, Point p) {
		if (currentlyGlowing != null) {
			currentlyGlowing.setGlow(false);
		}
		Network net=WorkspaceManager.getInstance().getNetwork();
		if(net==null) {
			return;
		}
		Collection<Node> ns=new ArrayList<Node>();
		ns.addAll(net.getAllBoderNodes());
		setGlow(node, p, ns);
	}
	
	private void setGlow(Node node, Point p, Collection<Node> ns) {
		Drawable d = getNearestNode(p, ns,30);
		if (d == null) {
			return;
		}
		if (node != null && ((Node) d.getModel()).getId().equals(node.getId())) {
			return;
		}
		if((d.getModel() instanceof Switch)==false) {
			return;
		}
		
		Switch sw = (Switch) d.getModel();
		if (sw.isComplete()) {
			return;
		}
		
		setGlow(d);

	}
	
	public void setGlow(Drawable d) {
		if(currentlyGlowing!=null) {
			currentlyGlowing.setGlow(false);
		}
		currentlyGlowing = d;
		
		if(d!=null) {
			d.setGlow(true);
		}
	}

	public Drawable getNearestNetworkNode(Point p) {
		if(WorkspaceManager.getInstance().getNetwork()!=null) {
			return getNearestNode(p, WorkspaceManager.getInstance().getNetwork().getAllNodes());
		}
		return null;
	}

	public Drawable getNearestNonNetworkNode(Point p) {
		if(WorkspaceManager.getInstance().getNetwork()!=null) {
			return getNearestNode(p, WorkspaceManager.getInstance().getNetwork().getAllBoderNodes());
		}
		return null;
	}
	
	public Drawable getNearestNetworkNode(Point p, int maxAllowed) {
		if(WorkspaceManager.getInstance().getNetwork()!=null) {
			return getNearestNode(p, WorkspaceManager.getInstance().getNetwork().getAllNodes(), maxAllowed);
		}
		return null;
	}
	
	
	private Drawable getNearestNode(Point p, Collection<Node> ds) {
		
		if(ds==null || ds.size()==0) {
			return null;
		}
		int maxAllowed = 0;
		if (Pad.getInstance().getZoom() > 15) {
			maxAllowed = 14;
		} else {
			maxAllowed = 10;
		}

		double closestDis = Double.MAX_VALUE;
		Node closest = null;
		for (Node sw : ds) {
			Point p2 = Pad.getInstance().getMapPosition(sw.getLat(), sw.getLon(), false);
			double dis = Math.abs(p2.distance(p));
			if (dis < closestDis) {
				closest = sw;
				closestDis = dis;
			}
		}
		if (closestDis < maxAllowed) {
			return getDrawable(closest);
		}
		return null;
	}
	
private Drawable getNearestNode(Point p, Collection<Node> ds, int maxAllowed) {
		
		if(ds==null || ds.size()==0) {
			return null;
		}

		double closestDis = Double.MAX_VALUE;
		Node closest = null;
		for (Node sw : ds) {
			Point p2 = Pad.getInstance().getMapPosition(sw.getLat(), sw.getLon(), false);
			double dis = Math.abs(p2.distance(p));
			if (dis < closestDis) {
				closest = sw;
				closestDis = dis;
			}
		}
		if (closestDis < maxAllowed) {
			return getDrawable(closest);
		}
		return null;
	}


	private Drawable getDrawable(Node closest) {
		if(closest instanceof RenderableObject) {
			RenderableObject ro=(RenderableObject)closest;
			return ro.getUI();
		}
		return null;
	}

	

	public void notifyComponents() {
		StatusBar.getInstance().updateDesignMode();
		NetworkTree.getInstance().updateTree();
		NodeGroupsPanel.getInstance().updateGroups();
		updateUI();
	}

	public Drawable getHighlighted() {
		if (currentlyHighlighted != null) {
			return currentlyHighlighted;
		}
		return null;
	}

	public void showCity(String selection) throws Exception {
		if (selection == null || selection.trim().length() == 0) {
			return;
		}
		MainFrame.getInstance().setCursor(Cursor.WAIT_CURSOR);
		HttpRequestor req = new HttpRequestor();
		Coordinate c = req.doLookup(selection);
		if(c!=null) {
			this.setDisplayPositionByLatLon(c.getLat(), c.getLon(), 14);
		}
		MainFrame.getInstance().setCursor(Cursor.DEFAULT_CURSOR);
	}

	public void setCursorLocation(Point point) {
		this.cursorPoint = point;

	}

	public void setGroupSelect(boolean b) {
		this.isGroupSelectEnabled = b;
		this.topLeftGroupCorner = null;
		this.bottomRightGroupCorner = null;
	}

	public boolean isGroupSelectEnabled() {
		return isGroupSelectEnabled;
	}

	public void setTopLeftGroupCorner(Point p) {
		this.topLeftGroupCorner = p;
	}

	public void setBottomRightGroupCorner(Point p) {
		this.bottomRightGroupCorner = p;
	}

	public boolean isCustomCursorSet() {
		return cursor!=null;
	}


	public void setDrawMergeLoad(boolean b) {
		this.drawMergeLoad=b;
		if(b==true && WorkspaceManager.getInstance().getNetwork()!=null) {
			Collection<Station> x=WorkspaceManager.getInstance().getNetwork().getAllStations();
			Station[] foos = x.toArray(new Station[x.size()]);
			MergeLoadCalculator.getInstance().calc(foos);
		}
		
	}
}

class CursorLocationUpdator implements MouseMotionListener {

	private Point p;

	@Override
	public void mouseDragged(MouseEvent me) {
		Pad.getInstance().setCursorLocation(me.getPoint());
		Pad.getInstance().updateUI();
	}

	@Override
	public void mouseMoved(MouseEvent me) {
		Pad.getInstance().setCursorLocation(me.getPoint());
		Pad.getInstance().updateUI();
	}

}
