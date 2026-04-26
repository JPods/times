package com.instinct.objects.network;

import java.util.Collection;

import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

public interface NodeGroup {
	public Collection<Node> getNodes();
	
	public void setCenter(Coordinate c);

	public void setHighlight(boolean isHighLight);

	public void removeGroup();
	
	public String getId();
	
	public void addNode(Node node);
	
	public JPopupMenu  getPopupMenu();
	
	public void move(Coordinate cord);

}
