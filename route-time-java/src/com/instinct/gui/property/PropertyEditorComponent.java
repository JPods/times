package com.instinct.gui.property;

import java.awt.BorderLayout;
import java.awt.Dimension;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.Insets;
import java.util.HashMap;
import java.util.Map;

import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTextField;

public class PropertyEditorComponent extends JPanel {

	private Map<String,AttributeEditor<?>> editors;
	private Map<String, AttributeEditor<?>> map = new HashMap<String, AttributeEditor<?>>();

	public PropertyEditorComponent(Map<String,AttributeEditor<?>> editors) {
		this.editors = editors;
		for (AttributeEditor<?> ae : editors.values()) {
			map.put(ae.getDisplayName(), ae);
		}
		buildUI();
	}

	private void buildUI() {
		this.setLayout(new BorderLayout());
		JPanel panel = new JPanel();
		panel.setLayout(new GridBagLayout());
		GridBagConstraints c = new GridBagConstraints();
		int y = 0;
		c.gridheight = 1;
		c.fill = GridBagConstraints.HORIZONTAL;
		c.ipadx = 10;
		c.ipadx = 5;
		c.insets = new Insets(5, 5, 5, 5);
		for (AttributeEditor<?> editor : editors.values()) {
			JLabel lbl = new JLabel(editor.getDisplayName());
			c.gridx = 0;
			c.gridy = y;
			c.gridwidth = 1;

			panel.add(lbl, c);
			JComponent editComp = editor.getEditor();
			editComp.setPreferredSize(new Dimension(100, 20));
			c.gridx = 1;
			c.gridwidth = 2;
			panel.add(editComp, c);
			y = y + 1;
		}
		this.add(BorderLayout.CENTER, panel);

	}

	public void setEditable(boolean isEditable) {
		for (AttributeEditor ae : map.values()) {
			if (ae.getEditor() instanceof JTextField) {
				JTextField comp = (JTextField) ae.getEditor();
				comp.setEditable(isEditable);
			}
		}

	}
}