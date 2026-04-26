package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddFenceAction extends AbstractAction {
	public AddFenceAction() {
		super("Fence", GUIUtil.getImage("line.png"));
		putValue(SHORT_DESCRIPTION, "Add Fence");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("line.png");

		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getLineAddFac());
		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getFenceAddFac());
	}
}




