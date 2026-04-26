package com.instinct.service.serialization;

import org.jdom2.Element;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Station;
import com.instinct.service.WorkspaceManager;

public class StationXMLSerializer implements XMLSerializer<Station> {


	
	@Override
	public Element serialize(Station t) {
		Element el = new Element(STATION);
		el.setAttribute(ID, t.getId());
		el.setAttribute(LAT, t.getLat()+"");
		el.setAttribute(LON, t.getLon()+"");
		return el;
	}

	@Override
	public Station deserialize(Element e) {
		String id=e.getAttributeValue(ID);
		double lat=Double.valueOf(e.getAttributeValue(LAT));
		double lon=Double.valueOf(e.getAttributeValue(LON));
		Station sw=new Station(id);
		sw.setPosition(lat, lon);
		WorkspaceManager.getInstance().getNetwork().addNode(sw);	
		return sw;
	}

}
