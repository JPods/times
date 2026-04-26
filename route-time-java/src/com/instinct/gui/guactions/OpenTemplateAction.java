package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class OpenTemplateAction extends AbstractAction {
	public OpenTemplateAction() {
		super("Open...", GUIUtil.getImage("open-file.png"));
		putValue(SHORT_DESCRIPTION, "Open Network");
		putValue(MNEMONIC_KEY, KeyEvent.VK_O);
		KeyBinder.getInstance().bind(KeyEvent.VK_O, this, "O");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		WorkspaceManager.getInstance().openFile();
	}
}