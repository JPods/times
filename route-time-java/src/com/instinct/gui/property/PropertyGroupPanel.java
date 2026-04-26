package com.instinct.gui.property;

import java.util.HashMap;
import java.util.Map;

import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.JPanel;

public class PropertyGroupPanel extends JPanel {
	private Map<String, PropertyPanel> panels=new HashMap<String, PropertyPanel>();
	private String groupName;
	public PropertyGroupPanel(String groupName, Map<String, String> props) {
		this.groupName=groupName;
		this.setBorder(BorderFactory.createTitledBorder(groupName));
		for (Map.Entry<String, String> e : props.entrySet()) {
			PropertyPanel property=new PropertyPanel(e.getKey(), e.getValue());
			this.add(property);
			this.add(Box.createHorizontalStrut(10));
			this.panels.put(e.getKey(), property);
		}

	}
	
	public void setProperty(String key, String value) {
		panels.get(key).setValue(value);
	}
	
	public String getGroupName() {
		return this.groupName;
	}

	public void setProperties(Map<String, String> v) {
		for (Map.Entry<String, String> e : v.entrySet()) {
			setProperty(e.getKey(),e.getValue());
		}
	}
}
