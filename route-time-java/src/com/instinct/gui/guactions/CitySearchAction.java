package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;
import javax.swing.JOptionPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;

public class CitySearchAction extends AbstractAction {
	public CitySearchAction() {
		super("Search City", GUIUtil.getImage("search.png"));
		putValue(SHORT_DESCRIPTION, "Enter Street, City, Country");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		String selection = JOptionPane.showInputDialog("Enter City, Country");
		try {
			Pad.getInstance().showCity(selection);
		} catch (Exception e) {
			e.printStackTrace();
		}
	}
}
