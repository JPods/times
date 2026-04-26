package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.StationGlass;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;

public class ShowStationZoomAction extends AbstractAction {
	public ShowStationZoomAction() {
		super("Station Zoom", GUIUtil.getImage("zoom.png"));
		
		putValue(SHORT_DESCRIPTION, "Zoom into station activity");
		putValue(MNEMONIC_KEY, KeyEvent.VK_Z);
		KeyBinder.getInstance().bind(KeyEvent.VK_Z, this, "Z");

	}

	public void actionPerformed(ActionEvent e) {

		Pad.getInstance().setCursorImage(null);

		
		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}
		StationGlass sg=StationGlass.getInstance();
		sg.display();
	}
}

