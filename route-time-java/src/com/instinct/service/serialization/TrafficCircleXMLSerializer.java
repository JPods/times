package com.instinct.service.serialization;

import org.jdom2.Element;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.TrafficCircle;
import com.instinct.service.WorkspaceManager;

public class TrafficCircleXMLSerializer implements XMLSerializer<TrafficCircle> {

	private static final String CIRCLE = "Circle";
	private static final String C1 = "C1";
	private static final String C2 = "C2";
	private static final String C3 = "C3";
	private static final String C4 = "C4";
	private static final String D1 = "D1";
	private static final String D2 = "D2";
	private static final String D3 = "D3";
	private static final String D4 = "D4";

	@Override
	public Element serialize(TrafficCircle t) {
		Element el = new Element(CIRCLE);
		el.setAttribute(ID, t.getId());
		el.setAttribute(C1, t.getC1().getId());
		el.setAttribute(C2, t.getC2().getId());
		el.setAttribute(C3, t.getC3().getId());
		el.setAttribute(C4, t.getC4().getId());
		el.setAttribute(D1, t.getD1().getId());
		el.setAttribute(D2, t.getD2().getId());
		el.setAttribute(D3, t.getD3().getId());
		el.setAttribute(D4, t.getD4().getId());
		return el;
	}

	@Override
	public TrafficCircle deserialize(Element e) {
		String id = e.getAttributeValue(ID);
		String c1Id = e.getAttributeValue(C1);
		String c2Id = e.getAttributeValue(C2);
		String c3Id = e.getAttributeValue(C3);
		String c4Id = e.getAttributeValue(C4);
		String d1Id = e.getAttributeValue(D1);
		String d2Id = e.getAttributeValue(D2);
		String d3Id = e.getAttributeValue(D3);
		String d4Id = e.getAttributeValue(D4);

		Switch c1 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(c1Id);
		Switch c2 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(c2Id);
		Switch c3 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(c3Id);
		Switch c4 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(c4Id);
		Switch d1 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(d1Id);
		Switch d2 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(d2Id);
		Switch d3 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(d3Id);
		Switch d4 = (Switch) WorkspaceManager.getInstance().getNetwork().getNode(d4Id);
		if (c1 != null & c2 != null && c3 != null && c4 != null && d1 != null && d2 != null && d3 != null && d4 != null) {
			TrafficCircle tc = new TrafficCircle(id, c1, d1, c2, d2, c3, d3, c4, d4);
			WorkspaceManager.getInstance().getNetwork().addGroup(tc);
			return tc;
		}
		return null;
	}

}
