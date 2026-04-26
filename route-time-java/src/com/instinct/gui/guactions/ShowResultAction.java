package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.ResultForm;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;
import com.instinct.service.WorkspaceManager;

public class ShowResultAction extends AbstractAction {
	public ShowResultAction() {
		super("Result", GUIUtil.getImage("result.png"));
		
		putValue(SHORT_DESCRIPTION, "Show Result");
		putValue(MNEMONIC_KEY, KeyEvent.VK_U);
		KeyBinder.getInstance().bind(KeyEvent.VK_U, this, "U");

	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		ResultForm.getInstance().show(WorkspaceManager.getInstance().getWorkingSim());
	}
}

