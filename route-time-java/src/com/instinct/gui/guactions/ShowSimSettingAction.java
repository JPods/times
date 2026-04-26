package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;

public class ShowSimSettingAction extends AbstractAction {
	
	public ShowSimSettingAction() {
		super("Configuration...", GUIUtil.getImage("settings.png"));
		
		putValue(SHORT_DESCRIPTION, "New Network");
		putValue(MNEMONIC_KEY, KeyEvent.VK_F);
		KeyBinder.getInstance().bind(KeyEvent.VK_F, this, "F");

	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()) {
			SimulationManager.getInstance().showSimulationSettingsForm();
		}
	}
}