package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddLineAction extends AbstractAction {
	public AddLineAction() {
		super("Line", GUIUtil.getImage("line.png"));
		putValue(SHORT_DESCRIPTION, "Add Line");
		putValue(MNEMONIC_KEY, KeyEvent.VK_L);
		KeyBinder.getInstance().bind(KeyEvent.VK_L, this, "L");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("line.png");

		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getLineAddFac());
	}
}




