package com.instinct.objects.network;

import java.util.Collection;

import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.service.WorkspaceManager;

public class TrafficCircle implements NodeGroup {

	private NodeGroupImpl nodeGroup=new NodeGroupImpl();
	private Coordinate center;
	private Switch c1,c2,c3,c4;
	private Switch d1,d2,d3,d4;
	
	private double r=0.0002;
	private String id="NG"+NodeGroupImpl.getNextID();


	public TrafficCircle(Coordinate c) {
		this.center=c;
		init();
	}
	
	
	public TrafficCircle(String id, Switch c1, Switch d1, Switch c2, Switch d2, Switch c3, Switch d3, Switch c4, Switch d4) {
		this.id=id;
		this.c1=c1;
		this.d1=d1;
		this.c2=c2;
		this.d2=d2;
		this.c3=c3;
		this.d3=d3;
		this.c4=c4;
		this.d4=d4;
		this.addNode(c1);
		this.addNode(c2);
		this.addNode(c3);
		this.addNode(c4);
		this.addNode(d1);
		this.addNode(d2);
		this.addNode(d3);
		this.addNode(d4);
		c1.setNodeGroup(this);
		c2.setNodeGroup(this);
		c3.setNodeGroup(this);
		c4.setNodeGroup(this);
		d1.setNodeGroup(this);
		d2.setNodeGroup(this);
		d3.setNodeGroup(this);
		d4.setNodeGroup(this);
		
		center=computeCenter();
	}

	private Coordinate computeCenter() {
		double lat=(c1.getLat()+c2.getLat()+c3.getLat()+c4.getLat()+d1.getLat()+d2.getLat()+d3.getLat()+d4.getLat())/8;
		double lon=(c1.getLon()+c2.getLon()+c3.getLon()+c4.getLon()+d1.getLon()+d2.getLon()+d3.getLon()+d4.getLon())/8;
		return new Coordinate(lat, lon);
	}


	public Coordinate getCenter() {
		return center;
	}

	public void setCenter(Coordinate p) {
		double diffLat=p.getLat()-center.getLat();
		double diffLon=p.getLon()-center.getLon();
		center=p;
		c1.setPosition(c1.getLat()+diffLat,c1.getLon()+diffLon);
		c2.setPosition(c2.getLat()+diffLat,c2.getLon()+diffLon);
		c3.setPosition(c3.getLat()+diffLat,c3.getLon()+diffLon);
		c4.setPosition(c4.getLat()+diffLat,c4.getLon()+diffLon);
		d1.setPosition(d1.getLat()+diffLat,d1.getLon()+diffLon);
		d2.setPosition(d2.getLat()+diffLat,d2.getLon()+diffLon);
		d3.setPosition(d3.getLat()+diffLat,d3.getLon()+diffLon);
		d4.setPosition(d4.getLat()+diffLat,d4.getLon()+diffLon);	
		
	}


	private void init() {
		c1=getSwitch(0);
		c2=getSwitch(90);
		c3=getSwitch(180);
		c4=getSwitch(270);
		d1=getSwitch(45);
		d2=getSwitch(135);
		d3=getSwitch(225);
		d4=getSwitch(315);
		join(c1, d1);
		join(d1, c2);
		join(c2, d2);
		join(d2, c3);
		join(c3, d3);
		join(d3, c4);
		join(c4, d4);
		join(d4, c1);
	}
	
	private Switch getSwitch(int degree) {
		Switch c=new SwitchImpl();
		double rad=Math.toRadians(degree);
		double lat= center.getLat()+r*Math.sin(rad);
		double lon= center.getLon()+r*Math.cos(rad);
		c.setPosition(lat,lon);
		WorkspaceManager.getInstance().getNetwork().addNode(c);
		this.addNode(c);
		c.setNodeGroup(this);
		return c;
	}
	

	private Line join(Switch c, Switch d) {
		Line line=new Line( c);
		line.setTrafficCircleId(id);
		line.setEnd(d);
		c.attachExitLine(line);
		d.attachEntryLine(line);
		WorkspaceManager.getInstance().getNetwork().addLine(line);
		return line;
	}


	@Override
	public Collection<Node> getNodes() {
		return nodeGroup.getNodes();
	}


	@Override
	public String getId() {
		return id;
	}


	@Override
	public String toString() {
		return "TrafficCircle [id=" + id + "]";
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
		TrafficCircle other = (TrafficCircle) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}


	public double getA() {
		return r;
	}


	public void setA(double a) {
		this.r = a;
	}


	@Override
	public void setHighlight(boolean isHighLight) {
		nodeGroup.setHighlight(isHighLight);
		
	}	
	
	@Override
	public void removeGroup() {
		nodeGroup.removeGroup();
		
	}

	@Override
	public void addNode(Node node) {
		nodeGroup.addNode(node);
		
	}

	public Switch getC1() {
		return c1;
	}

	public Switch getC2() {
		return c2;
	}

	public Switch getC3() {
		return c3;
	}

	public Switch getC4() {
		return c4;
	}

	public Switch getD1() {
		return d1;
	}

	public Switch getD2() {
		return d2;
	}

	public Switch getD3() {
		return d3;
	}

	public Switch getD4() {
		return d4;
	}

	public void setC1(Switch c1) {
		this.c1 = c1;
	}

	public void setC2(Switch c2) {
		this.c2 = c2;
	}

	public void setC3(Switch c3) {
		this.c3 = c3;
	}

	public void setC4(Switch c4) {
		this.c4 = c4;
	}

	public void setD1(Switch d1) {
		this.d1 = d1;
	}

	public void setD2(Switch d2) {
		this.d2 = d2;
	}

	public void setD3(Switch d3) {
		this.d3 = d3;
	}

	public void setD4(Switch d4) {
		this.d4 = d4;
	}


	@Override
	public JPopupMenu getPopupMenu() {
		return null;
	}


	@Override
	public void move(Coordinate c) {
		c1.move(c);
		c2.move(c);
		c3.move(c);
		c4.move(c);
		d1.move(c);
		d2.move(c);
		d3.move(c);
		d4.move(c);
		computeCenter();
	}
}
