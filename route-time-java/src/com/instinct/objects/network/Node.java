package com.instinct.objects.network;

import java.io.Serializable;

import org.openstreetmap.gui.jmapviewer.Coordinate;

public interface Node extends Serializable, Cloneable {

	public double getLat();
	public double getLon();
	public String getId();
	
	public void setPosition(double lat,double lon);

	public void setPosition(Node n);

	
	public void setPosition(Coordinate c);

	public void updateLineLengths();
	
	public String getName();
	
	public boolean isComplete();
	
	
	public NodeGroup getNodeGroup();
	
	public void setNodeGroup(NodeGroup nodeGrp);
	
	public boolean isNodeGroup();
	
	public void remove();
	
	public void removeWithinNodeGroup();
	
	
	public Node clone();
	
	public void move(Coordinate c);
	
}
