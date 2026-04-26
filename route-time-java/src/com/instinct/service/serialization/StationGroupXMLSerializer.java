package com.instinct.service.serialization;

import org.jdom2.Element;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.StationGroup;
import com.instinct.objects.network.Switch;
import com.instinct.service.WorkspaceManager;

public class StationGroupXMLSerializer implements XMLSerializer<StationGroup> {

	private static final String STATION_GRP = "StationGroup";
	private static final String C = "c";
	private static final String D = "d";
	private static final String ST = "st";

	@Override
	public Element serialize(StationGroup t) {
		Element el = new Element(STATION_GRP);
		el.setAttribute(ID, t.getId());
		el.setAttribute(C, t.getC().getId());
		el.setAttribute(D, t.getD().getId());
		el.setAttribute(ST, t.getStation().getId());
		return el;		
	}

	@Override
	public StationGroup deserialize(Element e) {
		String id=e.getAttributeValue(ID);
		String cId=e.getAttributeValue(C);
		String dId=e.getAttributeValue(D);
		String stId=e.getAttributeValue(ST);
		
		Switch c=(Switch)WorkspaceManager.getInstance().getNetwork().getNode(cId);
		Switch d=(Switch)WorkspaceManager.getInstance().getNetwork().getNode(dId);
		Station st=(Station)WorkspaceManager.getInstance().getNetwork().getNode(stId);
		
		if(c==null || d==null || st==null) {
			return null;
		}
		
		StationGroup tc=new StationGroup(id,c,d,st);
		WorkspaceManager.getInstance().getNetwork().addGroup(tc);
		return tc;
	}

}
