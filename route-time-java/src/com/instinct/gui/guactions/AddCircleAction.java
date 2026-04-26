package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddCircleAction extends AbstractAction {
	public AddCircleAction() {
		super("Circle", GUIUtil.getImage("circle.png"));
		putValue(SHORT_DESCRIPTION, "Add traffic circle");
		
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();
		Pad.getInstance().setCursorImage("circle.png");
		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getCircleAddFac());
	}
}


