package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.SavingDisplay;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class ShowEnergySavingAction extends AbstractAction {
	public ShowEnergySavingAction() {
		super("Savings", GUIUtil.getImage("money.png"));
		
		putValue(SHORT_DESCRIPTION, "Estimated Savings");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		
		Pad.getInstance().setCursorImage(null);

		if(WorkspaceManager.getInstance().getWorkingSim()==null) {
			Pad.getInstance().showAlert("No simulation");
			return; 
		}
		SavingDisplay display=new SavingDisplay();
		display.setVisible(true);
	}
}
