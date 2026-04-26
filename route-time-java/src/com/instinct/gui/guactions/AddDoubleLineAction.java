package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddDoubleLineAction extends AbstractAction {
	public AddDoubleLineAction() {
		super("Double Line", GUIUtil.getImage("double-line.png"));
		putValue(SHORT_DESCRIPTION, "Enter City, Country");
		putValue(MNEMONIC_KEY, KeyEvent.VK_D);
		KeyBinder.getInstance().bind(KeyEvent.VK_D, this, "D");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("double-line.png");

		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getDoubleLineFac());
	}
}



