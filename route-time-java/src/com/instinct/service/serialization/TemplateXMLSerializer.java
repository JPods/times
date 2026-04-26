package com.instinct.service.serialization;

import org.jdom2.Element;

import com.instinct.objects.XMLSerializer;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroupImpl;
import com.instinct.service.WorkspaceManager;

public class TemplateXMLSerializer implements XMLSerializer<NodeGroupImpl>{

	private static final String TEMPLATE = "tmpl";
	private static final String ID_LIST = "idList";

	
	@Override
	public Element serialize(NodeGroupImpl t) {
		Element el = new Element(TEMPLATE);
		el.setAttribute(ID, t.getId());
		StringBuilder sb=new StringBuilder();
		for(Node node:t.getNodes()) {
			sb.append(node.getId());
			sb.append(",");
		}
		el.setAttribute(ID_LIST, sb.toString());
		return el;
	}

	@Override
	public NodeGroupImpl deserialize(Element e) {
		String id=e.getAttributeValue(ID);
		NodeGroupImpl ng=new NodeGroupImpl(id);
		String idList=e.getAttributeValue(ID_LIST);
		String[] ids=idList.split(",");
		for(String i:ids) {
			if(i.trim().length()>0 && i.trim().equals(",")==false) {
				Node n=WorkspaceManager.getInstance().getNetwork().getNode(i);
				if(n!=null) {
					n.setNodeGroup(ng);
					ng.addNode(n);
				}
			}
		}
		WorkspaceManager.getInstance().getNetwork().addGroup(ng);
		return ng;
	}

}
