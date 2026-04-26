package com.instinct.objects.network;

import java.util.Collection;

import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.service.WorkspaceManager;

public class StationGroup  implements NodeGroup  {

	private Station st;
	private Switch c,d;
	private NodeGroupImpl nodeGroup=new NodeGroupImpl();
	private double a=35;
	
	private String id="NG"+NodeGroupImpl.getNextID();

	
	public StationGroup( Switch sw) {
		internalGraph(sw);
		Line graphEntryLine=sw.getEntry();
		Switch entryNode=(Switch) graphEntryLine.getStart();
		Line graphExitLine=sw.getExit();
		Switch exitNode=(Switch) graphExitLine.getEnd();

	
		Coordinate dPos=graphEntryLine.getCoordinateAt(Pad.getInstance(),graphEntryLine.getLength()-a);
		Coordinate cPos=graphExitLine.getCoordinateAt(Pad.getInstance(),a);
		d.setPosition(dPos);
		c.setPosition(cPos);
		
		entryNode.detachExitLine(graphEntryLine);
		Line newEntry=new Line((Node)entryNode);
		newEntry.setEnd(d);
		entryNode.attachExitLine(newEntry);
		d.attachEntryLine(newEntry);
		WorkspaceManager.getInstance().getNetwork().addLine(newEntry);
		
		exitNode.detachEntryLine(graphExitLine);
		Line newExit=new Line(c);
		newExit.setEnd((Node)exitNode);
		c.attachExitLine(newExit);
		exitNode.attachEntryLine(newExit);
		WorkspaceManager.getInstance().getNetwork().addLine(newExit);
		
		WorkspaceManager.getInstance().getNetwork().removeLine(graphEntryLine);
		WorkspaceManager.getInstance().getNetwork().removeLine(graphExitLine);
		
		
	}
	
	public StationGroup(String id) {
		this.id=id;
	}

	public StationGroup(String id, Switch c, Switch d, Station st) {
		this.id=id;
		this.c=c;
		this.d=d;
		this.st=st;
		c.setNodeGroup(this);
		d.setNodeGroup(this);
		st.setNodeGroup(this);
		addNode(c);
		addNode(d);
		addNode(st);
	}
	
	
	public Switch getC() {
		return c;
	}

	public Switch getD() {
		return d;
	}

	private void internalGraph(Switch sw) {
		st=new Station();
		st.setNodeGroup(this);
		st.setPosition(sw);
		nodeGroup.addNode(st);		
		WorkspaceManager.getInstance().getNetwork().addNode(st);
		
		c=new SwitchImpl();
		c.setNodeGroup(this);
		nodeGroup.addNode(c);		
		WorkspaceManager.getInstance().getNetwork().addNode(c);
		
		d=new SwitchImpl();
		d.setNodeGroup(this);
		nodeGroup.addNode(d);
		WorkspaceManager.getInstance().getNetwork().addNode(d);
		
		Line entry=new Line(d);
		entry.setEnd(st);
		st.setEntry(entry);
		d.attachExitLine(entry);
		WorkspaceManager.getInstance().getNetwork().addLine(entry);

		Line exit=new Line(st);
		exit.setEnd(c);
		st.setExit(exit);
		c.attachEntryLine(exit);
		WorkspaceManager.getInstance().getNetwork().addLine(exit);

		
		Line pass=new Line(d);
		d.attachExitLine(pass);
		pass.setEnd(c);
		c.attachEntryLine(pass);
		WorkspaceManager.getInstance().getNetwork().addLine(pass);

		
	}
	
	@Override
	public Collection<Node> getNodes() {
		return nodeGroup.getNodes();
	}

	@Override
	public void setCenter(Coordinate p) {
		double diffLat=p.getLat()-st.getLat();
		double diffLon=p.getLon()-st.getLon();
		st.setPosition(p);
		c.setPosition(c.getLat()+diffLat,c.getLon()+diffLon);
		d.setPosition(d.getLat()+diffLat,d.getLon()+diffLon);
	}
	
	
	@Override
	public void setHighlight(boolean isHighLight) {
		nodeGroup.setHighlight(isHighLight);
	}	
	
	
	@Override
	public String getId() {
		return id;
	}


	@Override
	public String toString() {
		return "StationGroup [id=" + id + "]";
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
		StationGroup other = (StationGroup) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}

	@Override
	public void removeGroup() {
		nodeGroup.removeGroup();
		
	}
	
	public void setDivergence(Switch s) {
		d=s;
		nodeGroup.addNode(s);
	}
	
	
	public void setConvergence(Switch s) {
		c=s;
		nodeGroup.addNode(s);
	}
	
	@Override
	public void addNode(Node n) {
		nodeGroup.addNode(n);

	}

	public Station getStation() {
		return st;
	}

	@Override
	public JPopupMenu getPopupMenu() {
		return null;
	}

	@Override
	public void move(Coordinate cord) {
		c.move(cord);
		d.move(cord);
		st.move(cord);
	}


}

