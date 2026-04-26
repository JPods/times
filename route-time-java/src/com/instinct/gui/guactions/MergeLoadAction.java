package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;

public class MergeLoadAction extends AbstractAction {
	public MergeLoadAction() {
		super("Achilles heel", GUIUtil.getImage("result.png"));
		
		putValue(SHORT_DESCRIPTION, "Show Loads on th Merges");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		Pad.getInstance().setDrawMergeLoad(true);
	}
}

