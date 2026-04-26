package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class ClearNetworkAction extends AbstractAction {
	public ClearNetworkAction() {
		super("Clear", GUIUtil.getImage("clear.png"));
		putValue(SHORT_DESCRIPTION, "This will clear the Network");
		putValue(MNEMONIC_KEY, KeyEvent.VK_E);
		KeyBinder.getInstance().bind(KeyEvent.VK_E, this, "E");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		WorkspaceManager.getInstance().clearNetwork();
	}
}

