package com.instinct.service.serialization;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.swing.JOptionPane;

import org.jdom2.Document;
import org.jdom2.Element;
import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.NodeGroupImpl;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.WorkspaceManager;

public class MergingService implements SerializationConstants {
	
	private Map<String, String> oldNewIdMap=new HashMap<String, String>();
	
	private List<Node> nodes=new ArrayList<Node>();
	
	private List<Line> lines=new ArrayList<Line>();

	private double originLat;

	private double originLon;
	
	private NodeGroup ng;
	
	private static String ID="ID";
	
	
	
	public void  merge(Document doc, double newLat, double newLon) {
		ng=new NodeGroupImpl("NG-"+NodeGroupImpl.getNextID());
		Element root=doc.getRootElement();
		List<Element> swEls=root.getChildren(SWITCHES);
		for(Element el:swEls.get(0).getChildren()) {
			deserializeSwitch(ng,el);
		}
		
		List<Element> stEls=root.getChildren(STATIONS);
		for(Element el:stEls.get(0).getChildren()) {
			deserializeStation(ng, el);
		}
		
		List<Element> lineEls=root.getChildren(LINES);
		for(Element el:lineEls.get(0).getChildren()) {
			deserializeLine(el);
		}
		

		WorkspaceManager.getInstance().getNetwork().addGroup(ng);
		Coordinate c=computeMapCenter();
		this.originLat=c.getLat();
		this.originLon=c.getLon();
		relocate(newLat, newLon);
	}


	private void relocate(double newLat, double newLon) {
		for(Node n:nodes) {
			double lat=newLat+(n.getLat()-originLat);
			double lon=newLon+(n.getLon()-originLon);
			n.setPosition(lat, lon);
		}
		
		for(Line l:lines) {
			for(Coordinate c:l.getCoordinates()) {
				double lat=newLat+(c.getLat()-originLat);
				double lon=newLon+(c.getLon()-originLon);
				c.setLat(lat);
				c.setLon(lon);
			}
		}
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
		return new Coordinate(latTotal / total, lonTotal / total);
	}
	

	private void deserializeLine(Element e) {
		String id=e.getAttributeValue(ID);
		String startId=e.getAttributeValue(LineXMLSerializer.START_NODE_ID);
		String endId=e.getAttributeValue(LineXMLSerializer.END_NODE_ID);
		
		Node start=WorkspaceManager.getInstance().getNetwork().getNode(oldNewIdMap.get(startId));
		Node end=WorkspaceManager.getInstance().getNetwork().getNode(oldNewIdMap.get(endId));
		List<Coordinate> list=new ArrayList<Coordinate>();
		
		for(Element e1:e.getChildren()) {
			Coordinate c=new Coordinate(Double.valueOf(e1.getAttributeValue(XMLSerializer.LAT)), Double.valueOf(e1.getAttributeValue(XMLSerializer.LON)));
			list.add(c);
		}
		Line line=new Line(start);
		line.setCoordinates(list);
		line.setEnd(end);
		
		
		lines.add(line);
		WorkspaceManager.getInstance().getNetwork().addLine(line);

		if(start instanceof Station) {
			((Station)start).setExit(line);
		} else {
			((Switch)start).attachExitLine(line);
		}
		
		if(end instanceof Station) {
			((Station)end).setEntry(line);
		} else {
			((Switch)end).attachEntryLine(line);
		}
		
	}

	private void deserializeStation(NodeGroup ng, Element e) {
		String id=e.getAttributeValue(ID);
		double lat=Double.valueOf(e.getAttributeValue(XMLSerializer.LAT));
		double lon=Double.valueOf(e.getAttributeValue(XMLSerializer.LON));
		Station sw=new Station();
		sw.setPosition(lat, lon);
		sw.setNodeGroup(ng);
		ng.addNode(sw);
		oldNewIdMap.put(id, sw.getId());
		nodes.add(sw);
		WorkspaceManager.getInstance().getNetwork().addNode(sw);	
	}

	private void deserializeSwitch(NodeGroup ng, Element e) {
		String id=e.getAttributeValue(ID);
		double lat=Double.valueOf(e.getAttributeValue(XMLSerializer.LAT));
		double lon=Double.valueOf(e.getAttributeValue(XMLSerializer.LON));
		SwitchImpl sw=new SwitchImpl();
		sw.setPosition(lat, lon);
		sw.setNodeGroup(ng);
		ng.addNode(sw);
		oldNewIdMap.put(id, sw.getId());
		nodes.add(sw);
		WorkspaceManager.getInstance().getNetwork().addNode(sw);
		
	}

	public void unmerge() {
		for(Node node:nodes) {
			WorkspaceManager.getInstance().getNetwork().removeNode(node);
		}
		
		for(Line line:lines) {
			WorkspaceManager.getInstance().getNetwork().removeLine(line);
		}
		
		WorkspaceManager.getInstance().getNetwork().removeGroup(ng.getId());
		
	}
}
