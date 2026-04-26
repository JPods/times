package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddSwitchAction extends AbstractAction {
	public AddSwitchAction() {
		super("Switch", GUIUtil.getImage("switch.png"));
		putValue(SHORT_DESCRIPTION, "Add Switch");
		putValue(MNEMONIC_KEY, KeyEvent.VK_W);
		KeyBinder.getInstance().bind(KeyEvent.VK_W, this, "W");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("switch.png");
		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getSwitchAddFac());
	}
}

