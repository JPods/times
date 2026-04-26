package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;
import javax.swing.JOptionPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class SaveAsAction extends AbstractAction {
	public SaveAsAction() {
		super("Save As...", GUIUtil.getImage("save-as.png"));

		putValue(SHORT_DESCRIPTION, "Save as Network");
		putValue(MNEMONIC_KEY, KeyEvent.VK_A);
		KeyBinder.getInstance().bind(KeyEvent.VK_A, this, "A");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		String s = WorkspaceManager.getInstance().getValidationString();
		if (s != null && s.length() > 0) {
			JOptionPane.showConfirmDialog(MainFrame.getInstance(), s);
		} 
		WorkspaceManager.getInstance().saveAsFile();
	}
}