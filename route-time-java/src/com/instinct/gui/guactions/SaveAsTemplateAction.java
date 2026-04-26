package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;
import javax.swing.JOptionPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.gui.tree.TemplatesPanel;
import com.instinct.service.TemplateManager;
import com.instinct.service.WorkspaceManager;

public class SaveAsTemplateAction extends AbstractAction {
	public SaveAsTemplateAction() {
		super("Save As Template...", GUIUtil.getImage("save-template.png"));

		putValue(SHORT_DESCRIPTION, "Save as Template");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);
		try {
			TemplateManager.getInstance().saveAsTemplateFile();
			TemplatesPanel.getInstance().updateTemplates();
		} catch (Exception e1) {
			e1.printStackTrace();
		}
	}
}