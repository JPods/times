package com.instinct.gui.guactions;

import java.awt.Cursor;
import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.service.SimulationManager;
import com.instinct.service.TimeGraphMouseHandler;

public class ShowTimeMapAction extends AbstractAction {
	public ShowTimeMapAction() {
		super("Route Time", GUIUtil.getImage("map.png"));
		
		putValue(SHORT_DESCRIPTION, "Show Route Time");
		putValue(MNEMONIC_KEY, KeyEvent.VK_T);
		KeyBinder.getInstance().bind(KeyEvent.VK_T, this, "T");

	}

	public void actionPerformed(ActionEvent e) {
		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		Pad.getInstance().setCursor(new Cursor(Cursor.CROSSHAIR_CURSOR));
		Pad.getInstance().addMouseListener(TimeGraphMouseHandler.getInstance());
	}
}

