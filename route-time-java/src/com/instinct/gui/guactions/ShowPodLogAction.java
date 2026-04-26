package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.PodLogForm;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;

public class ShowPodLogAction extends AbstractAction {
	public ShowPodLogAction() {
		super("Log View...", GUIUtil.getImage("log.png"));
		
		putValue(SHORT_DESCRIPTION, "View log of individual Pod");
		putValue(MNEMONIC_KEY, KeyEvent.VK_V);
		KeyBinder.getInstance().bind(KeyEvent.VK_V, this, "V");

	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		PodLogForm rf=PodLogForm.getInstance();
		rf.display();	
	}
}

