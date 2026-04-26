package com.instinct.service.serialization;

import java.util.ArrayList;
import java.util.List;

import org.jdom2.Element;
import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.service.WorkspaceManager;

public class LineXMLSerializer implements XMLSerializer<Line> {


	public static final String START_NODE_ID = "startNodeId";

	public static final String END_NODE_ID = "endNodeId";

	public static final String TRAFFIC_CIRCLE_ID = "tcId";

	public static final String LINE = "line";

	public static final String COORDINATE = "Coordinate";
	
	
	@Override
	public Element serialize(Line t) {
		Element el = new Element(LINE);
		el.setAttribute(ID, t.getId());
		el.setAttribute(START_NODE_ID, t.getStart().getId());
		el.setAttribute(END_NODE_ID, t.getEnd().getId());
		el.setAttribute(IS_NETWORK_EL, t.isNetworkElement()+"");
		if(t.getTrafficCircleId()!=null) {
			el.setAttribute(TRAFFIC_CIRCLE_ID, t.getTrafficCircleId());
		}
		for(Coordinate c:t.getCoordinates()) {
			Element cEl = new Element(COORDINATE);
			cEl.setAttribute(LAT, c.getLat()+"");
			cEl.setAttribute(LON, c.getLon()+"");
			el.addContent(cEl);

		}
		return el;		
	}

	@Override
	public Line deserialize(Element e) {
		String id=e.getAttributeValue(ID);
		String startId=e.getAttributeValue(START_NODE_ID);
		String endId=e.getAttributeValue(END_NODE_ID);
		Node start=null;
		Node end=null;
		boolean isNetEl=false;
		String tcId=null;
		if(e.getAttribute(TRAFFIC_CIRCLE_ID)!=null) {
			tcId=e.getAttributeValue(TRAFFIC_CIRCLE_ID);
		}
		
		if(e.getAttribute(IS_NETWORK_EL)==null) {
			isNetEl=true;
		} else {
			isNetEl=Boolean.valueOf(e.getAttributeValue(IS_NETWORK_EL));
		}
		
		if(isNetEl) {
			start=WorkspaceManager.getInstance().getNetwork().getNode(startId);
			end=WorkspaceManager.getInstance().getNetwork().getNode(endId);
		} else {
			start=WorkspaceManager.getInstance().getNetwork().getBoundaryNode(startId);
			
			if(start==null) {
				start=WorkspaceManager.getInstance().getNetwork().getNode(startId);
				if(start!=null) {
					System.out.println(start.getId()+" found in the worng bucket");
				}
				
			}
			end=WorkspaceManager.getInstance().getNetwork().getBoundaryNode(endId);
			if(end==null) {
				end=WorkspaceManager.getInstance().getNetwork().getNode(endId);
				if(end!=null) {
					System.out.println(end.getId()+" found in the worng bucket");
				}
			}
		}
		List<Coordinate> list=new ArrayList<Coordinate>();
		
		for(Element e1:e.getChildren()) {
			Coordinate c=new Coordinate(Double.valueOf(e1.getAttributeValue(LAT)), Double.valueOf(e1.getAttributeValue(LON)));
			list.add(c);
		}
		
		if(start==null || end==null) {
			System.out.println("End/Start not found");
			return null;
		}
		Line line=new Line(id, start, end,list);
		line.setTrafficCircleId(tcId);
		line.setNetworkElement(isNetEl);

		if(line.isNetworkElement()) {
			WorkspaceManager.getInstance().getNetwork().addLine(line);
		} else {
			WorkspaceManager.getInstance().getNetwork().addBoundaryLine(line);
		}
		
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
		

		return line;
	}



}
