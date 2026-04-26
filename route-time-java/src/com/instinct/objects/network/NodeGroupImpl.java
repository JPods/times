package com.instinct.objects.network;

import java.awt.Point;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import javax.swing.JMenuItem;
import javax.swing.JOptionPane;
import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.service.WorkspaceManager;

public class NodeGroupImpl implements NodeGroup, Cloneable {

	private List<Node> nodes=new ArrayList<Node>();
	private Coordinate center;
	private String id;
	private JPopupMenu popup;
	private double originLat;
	private double originLon;
	private boolean isTrafficCircle=false;
	private static AtomicInteger idGen=new AtomicInteger(0);		

	public NodeGroupImpl() {
		this("NG-"+NodeGroupImpl.getNextID());
	}
	
	public boolean isTrafficCircle() {
		return isTrafficCircle;
	}

	private void buildMenu() {
		popup = new JPopupMenu();
		final NodeGroupImpl reference=this;
		ActionListener rotateActionListener=new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				if(ae.getActionCommand().equals("Delete")) {
					delete();
				} else if(ae.getActionCommand().contains("...")) {
					String input=JOptionPane.showInputDialog(MainFrame.getInstance(), "Enter degree");
					rotate(Integer.parseInt(input));
				} else {
					 String intStr=ae.getActionCommand().replace("Degree","").replace("Rotate","").trim();
					 int degree=Integer.parseInt(intStr);
					 rotate(degree);
				}
			}
			
		};
		JMenuItem item;
	    popup.add(item = new JMenuItem("Rotate 90 Degree"));
	    item.addActionListener(rotateActionListener);
	    popup.add(item = new JMenuItem("Rotate 180 Degree"));
	    item.addActionListener(rotateActionListener);
	    popup.add(item = new JMenuItem("Rotate 270 Degree"));
	    item.addActionListener(rotateActionListener);
	    popup.add(item = new JMenuItem("Rotate ..."));
	    item.addActionListener(rotateActionListener);
	    popup.add(item = new JMenuItem("Delete"));
	    item.addActionListener(rotateActionListener);

	}

	public NodeGroupImpl clone() {
		return null;
		
	}

	private void delete() {
		removeGroup();
		WorkspaceManager.getInstance().getNetwork().removeGroup(id);
		NetworkTree.getInstance().updateTree();
		NodeGroupsPanel.getInstance().updateGroups();
		Pad.getInstance().updateUI();
		
	}

	
	public NodeGroupImpl(String id) {
		this.id=id;
		buildMenu();
	}

	public Collection<Node> getNodes() {
		return nodes;
	}
	
	public void addNode(Node node) {
		nodes.add(node);
	}

	@Override
	public String toString() {
		return id;
	}

	public void setHighlight(boolean isHighLight) {
		for(Node n:nodes) {
			RenderableObject<?> ro=(RenderableObject<?>) n;
			ro.getUI().setHighlight(isHighLight);
		}
		
	}

	public void removeGroup() {
		for(Node n:nodes) {
			n.removeWithinNodeGroup();
		}
	}
	
	public static int getNextID() {
		return idGen.getAndIncrement();
	}

	public static int getLastId() {
		return idGen.get();
	}

	public static void setLastId(int lastId) {
		idGen.set(lastId+1);
		
	}

	private Coordinate computeCenter() {
		double latT=0;
		double lonT=0;
		if(nodes.size()==0) {
			return null;
		}
		for(Node n:nodes) {
			latT=latT+n.getLat();
			lonT=lonT+n.getLon();
		}
		return new Coordinate(latT/nodes.size(), lonT/nodes.size());
	}

	public void setCenter(Coordinate p) {
		if(center==null) {
			center=computeCenter();
		}
		double diffLat=p.getLat()-center.getLat();
		double diffLon=p.getLon()-center.getLon();
		center=p;
		for(Node n:nodes) {
			n.setPosition(n.getLat()+diffLat, n.getLon()+diffLon);
		}
	}

	@Override
	public String getId() {
		if(id!=null) {
			return id;
		}
		return "NG-1";
	}

	@Override
	public JPopupMenu getPopupMenu() {
		return popup;
	}
	
	public Coordinate computeMapCenter() {
		double total = 0;
		double latTotal = 0;
		double lonTotal = 0;
		for (Node st : nodes) {
			total++;
			latTotal += st.getLat();
			lonTotal += st.getLon();
		}
		this.originLat=latTotal / total;
		this.originLon=lonTotal / total;
		return new Coordinate(originLat, originLon);
	}
	
	private void rotate(int degree) {
		computeMapCenter();
		for(Node n:nodes) {
			Coordinate rotatedC=rotateCordinate(degree, new Coordinate(n.getLat(), n.getLon()));
			n.setPosition(rotatedC);
		}
		Pad.getInstance().updateUI();
	}

	private Coordinate rotateCordinate(int degree, Coordinate c) {
		Point p1=Pad.getInstance().getMapPosition(c, false);
		Point origin=Pad.getInstance().getMapPosition(originLat, originLon, false);
		double radian = Math.toRadians(degree);
		double newX = origin.x + ( Math.cos(radian) * (p1.x-origin.x) + Math.sin(radian) * (p1.y -origin.y));
		double newY = origin.y + (-Math.sin(radian) * (p1.x-origin.x) +Math.cos(radian) * (p1.y -origin.y));
		Coordinate newC=Pad.getInstance().getPosition((int)newX, (int)newY);
		return newC;
	
	}
	
	public void move(Coordinate cord) {
		for(Node n:getNodes())  {
			n.move(cord);
		}
		
	}
}
