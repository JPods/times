package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class NewNetworkAction extends AbstractAction {
	public NewNetworkAction() {
		
		super("New", GUIUtil.getImage("new.png"));
		
		putValue(SHORT_DESCRIPTION, "New Network");
		putValue(MNEMONIC_KEY, KeyEvent.VK_N);
		
		KeyBinder.getInstance().bind(KeyEvent.VK_N, this, "N");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();
		Pad.getInstance().setCursorImage(null);
		WorkspaceManager.getInstance().newFile();
	}
}