package com.instinct.service.serialization;

import java.util.ArrayList;
import java.util.List;

import org.jdom2.Document;
import org.jdom2.Element;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.NodeGroupImpl;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.StationGroup;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.objects.network.TrafficCircle;
import com.instinct.service.WorkspaceManager;

public class SerializationService implements SerializationConstants {

	
	private LineXMLSerializer lineSr=new LineXMLSerializer();
	private SwitchXMLSerializer swSr=new SwitchXMLSerializer();
	private StationXMLSerializer stSr=new StationXMLSerializer();
	private StationGroupXMLSerializer sgSr=new StationGroupXMLSerializer();
	private TrafficCircleXMLSerializer tcSr=new TrafficCircleXMLSerializer();
	private TemplateXMLSerializer tmplSr=new TemplateXMLSerializer();
	
	public Document serialize(Network net) {
		//adjustLines(net);
		
		Element root = new Element("network");
		root.setAttribute(ID, net.getName());
		if(net.getVersionId()==0) {
			net.setVersionId(System.currentTimeMillis());
		}
		root.setAttribute(VERSION, net.getVersionId()+"");
		Document doc = new Document(root);

		Element sws = new Element(SWITCHES);
		sws.setAttribute(LAST_ID, SwitchImpl.getLastId()+"");
		root.addContent(sws);
		for(Switch n:net.getAllSwitchs()) {
			Element e=swSr.serialize(n);
			sws.addContent(e);
		}
		
		for(Node n:net.getAllBoderNodes()) {
			Element e=swSr.serialize((Switch)n);
			sws.addContent(e);
		}
		
		Element sts = new Element(STATIONS);
		root.addContent(sts);
		sts.setAttribute(LAST_ID, Station.getLastId()+"");
		for(Station n:net.getAllStations()) {
			Element e=stSr.serialize(n);
			sts.addContent(e);
		}
		
		
		Element lines = new Element(LINES);
		lines.setAttribute(LAST_ID, Line.getLastId()+"");
		root.addContent(lines);
		for(Line n:net.getAllLines()) {
			Element e=lineSr.serialize(n);
			lines.addContent(e);
		}
		
		for(Line n:net.getAllBorderLines()) {
			Element e=lineSr.serialize(n);
			lines.addContent(e);
		}

		Element nodeGrps = new Element(GROUPS);
		nodeGrps.setAttribute(LAST_ID, NodeGroupImpl.getLastId()+"");
		root.addContent(nodeGrps);
		for(NodeGroup n:net.getAllGroups()) {
			Element e=null;
			if(n instanceof StationGroup) {
				e=sgSr.serialize((StationGroup) n);
				e.setAttribute(TYPE, STATION_GROUP_TYPE);
				nodeGrps.addContent(e);
			} else if (n instanceof TrafficCircle) {
				e=tcSr.serialize((TrafficCircle) n);
				e.setAttribute(TYPE, CIRCLE_TYPE);
				nodeGrps.addContent(e);
			} else if (n instanceof NodeGroupImpl) {
				e=tmplSr.serialize((NodeGroupImpl) n);
				e.setAttribute(TYPE, TEMPLATE);
				nodeGrps.addContent(e);
			} 
		}
		return doc;
	}

	private void adjustLines(Network net) {
		List<String> lines=new ArrayList<String>();
		addTc(lines, 16, 23);
		addTc(lines, 24, 31);
		addTc(lines, 32, 39);
		addTc(lines, 40, 47);
		addTc(lines, 56, 63);
		addTc(lines, 112, 119);
		addTc(lines, 144, 151);
		addTc(lines, 152, 159);
		addTc(lines, 160, 167);
		addTc(lines, 168, 175);
		addTc(lines, 538, 545);
		addTc(lines, 546, 553);
		addTc(lines, 554, 561);
		addTc(lines, 720, 727);
		addTc(lines, 768, 787);
		addTc(lines, 794, 801);
		addTc(lines, 900, 907);
		addTc(lines, 920, 927);
		addTc(lines, 940, 947);
		addTc(lines, 978, 985);
		addTc(lines, 1009, 1016);
		addTc(lines, 1029, 1036);
		addTc(lines, 1049, 1056);
		addTc(lines, 1069, 1076);
		addTc(lines, 1089, 1096);
		addTc(lines, 1109, 1116);
		addTc(lines, 1149, 1156);
		addTc(lines, 1169, 1176);
		addTc(lines, 1198, 1205);


		for(String s:lines) {
			net.getLine(s).setTrafficCircleId("tc1");
		}
		
	}
	
	private void addTc(List<String> lines, int start, int end) {
		System.out.println(" TC saved :"+start+", "+end);
		for(int i=start;i<=end;i++) {
			lines.add("L"+i);
		}
	}

	public void  deserialize(Document doc) {
		Element root=doc.getRootElement();
		WorkspaceManager.getInstance().createNetwork(root.getAttributeValue(ID));
		Network net=WorkspaceManager.getInstance().getNetwork();
		String version=root.getAttributeValue(VERSION);
		if(version==null) {
			System.out.println("Version regenerated");
			version=System.currentTimeMillis()+"";
		}
		net.setVersionId(Long.parseLong(version));
		int lastId=0;
		List<Element> swEls=root.getChildren(SWITCHES);
		lastId=getLastId(swEls);
		SwitchImpl.setLastId(lastId);
		for(Element el:swEls.get(0).getChildren()) {
			swSr.deserialize(el);
		}
		
		List<Element> stEls=root.getChildren(STATIONS);
		lastId=getLastId(stEls);
		Station.setLastId(lastId);
		for(Element el:stEls.get(0).getChildren()) {
			stSr.deserialize(el);
		}
		
		List<Element> lineEls=root.getChildren(LINES);
		lastId=getLastId(lineEls);
		Line.setLastId(lastId);
		for(Element el:lineEls.get(0).getChildren()) {
			lineSr.deserialize(el);
		}
		
		List<Element> groupsEls=root.getChildren(GROUPS);
		lastId=getLastId(groupsEls);
		NodeGroupImpl.setLastId(lastId);
		for(Element el:groupsEls.get(0).getChildren()) {
			String type=el.getAttributeValue(TYPE);
			if(type.equals(STATION_GROUP_TYPE)) {
				sgSr.deserialize(el);
			} else if (type.equals(CIRCLE_TYPE)) {
				tcSr.deserialize(el);
			} else if (type.equals(TEMPLATE)) {
				tmplSr.deserialize(el);
			} 
		}
		
		
	}

	private int getLastId(List<Element> groupsEls) {
		String t=groupsEls.get(0).getAttributeValue(LAST_ID);
		return Integer.valueOf(t);
	}
	
	
	
	
}
