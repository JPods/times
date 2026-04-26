package com.instinct.service.serialization;

import org.jdom2.Element;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.WorkspaceManager;

public class SwitchXMLSerializer implements XMLSerializer<Switch> {

	@Override
	public Element serialize(Switch t) {
		Element el = new Element(SWITCH);
		el.setAttribute(ID, t.getId());
		el.setAttribute(LAT, t.getLat() + "");
		el.setAttribute(LON, t.getLon() + "");
		if(t.isNetworkElement()) {
			el.setAttribute(IS_NETWORK_EL, "true");
		} else {
			el.setAttribute(IS_NETWORK_EL, "false");
			
		}
		return el;
	}

	@Override
	public Switch deserialize(Element e) {
		String id=e.getAttributeValue(ID);
		
		if(id.equalsIgnoreCase("SW296")) {
			System.out.println(345);
		}
		double lat=Double.valueOf(e.getAttributeValue(LAT));
		double lon=Double.valueOf(e.getAttributeValue(LON));
		SwitchImpl sw=new SwitchImpl(id);
		
		if(e.getAttribute(IS_NETWORK_EL)==null) {
			sw.setNetworkElement(true);
		} else {
			boolean isNetworkEl=Boolean.valueOf(e.getAttributeValue(IS_NETWORK_EL));
			sw.setNetworkElement(isNetworkEl);
		}
		sw.setPosition(lat, lon);
		if(sw.isNetworkElement()) {
			WorkspaceManager.getInstance().getNetwork().addNode(sw);
		} else {
			WorkspaceManager.getInstance().getNetwork().addBoundaryNode(sw);
		}
		
		return sw;
		
	}
}
