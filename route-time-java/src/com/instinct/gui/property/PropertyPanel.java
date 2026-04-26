package com.instinct.gui.property;

import java.awt.Font;

import javax.swing.JLabel;
import javax.swing.JPanel;

public class PropertyPanel extends JPanel {
	
	private String key;
	private JLabel valueLbl;
	public PropertyPanel(String key, String value) {
		this.key=key;
		JLabel lbl1 = new JLabel(key);
		Font font1 = new Font("Arial", Font.BOLD, 10);
		lbl1.setFont(font1);
		valueLbl = new JLabel(value);
		Font font2 = new Font("Arial", Font.PLAIN, 10);
		valueLbl.setFont(font2);
		this.add(lbl1);
		this.add(valueLbl);
	}
	
	
	public String getKey() {
		return key;
	}

	
	public void setValue(String value) {
		this.valueLbl.setText(value);
	}
	
	
}
