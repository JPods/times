package com.instinct.gui;

import java.awt.Color;
import java.awt.Component;

import javax.swing.JLabel;
import javax.swing.JTable;
import javax.swing.table.TableCellRenderer;

import com.instinct.config.TimeColor;
import com.instinct.service.WorkspaceManager;

public class TimeGridCellRenderer extends JLabel implements TableCellRenderer {
	public TimeGridCellRenderer() {
		setOpaque(true); // MUST do this for background to show up.
	}

	public Component getTableCellRendererComponent(JTable table, Object value, boolean isSelected, boolean hasFocus, int row, int column) {
		int t=(Integer)value;
		Color c=Color.BLACK;
		if(t<Integer.MAX_VALUE) {
			c=TimeColor.getColor(t*WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()).getColor();
		}
		setText(t+"");
		setBackground(c);
		return this;
	}
}