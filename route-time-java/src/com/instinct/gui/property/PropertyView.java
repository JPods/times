package com.instinct.gui.property;

import java.util.HashMap;
import java.util.Map;

import javax.swing.JPanel;

public class PropertyView extends JPanel {

	private Map<String, PropertyGroupPanel> groups=new HashMap<String,PropertyGroupPanel>();
	public void setProperty(String key, Map<String,String> v) {
		if(!groups.containsKey(key)) {
			PropertyGroupPanel p=new PropertyGroupPanel(key, v);
			groups.put(key, p);
			this.add(p);
		} else {
			groups.get(key).setProperties(v);
		}
	}
}
