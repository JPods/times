package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.TimeGrid;
import com.instinct.gui.pad.Pad;
import com.instinct.service.SimulationManager;

public class ShowTimeGridAction extends AbstractAction {
	public ShowTimeGridAction() {
		super("Route Grid", GUIUtil.getImage("grid.png"));
		
		putValue(SHORT_DESCRIPTION, "Show time distances between every pair of stations");
		putValue(MNEMONIC_KEY, KeyEvent.VK_G);
		KeyBinder.getInstance().bind(KeyEvent.VK_G, this, "G");

	}

	public void actionPerformed(ActionEvent e) {
		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		TimeGrid.getInstance().setVisible(true);
	}
}
