package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;
import javax.swing.JOptionPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimResultManager;
import com.instinct.service.WorkspaceManager;

public class SaveSimulationAction extends AbstractAction {
	public SaveSimulationAction() {
		super("Save Simulation...", GUIUtil.getImage("save-as.png"));

		putValue(SHORT_DESCRIPTION, "Save Simulation");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		String s = WorkspaceManager.getInstance().getValidationString();
		if (s != null && s.length() > 0) {
			JOptionPane.showConfirmDialog(MainFrame.getInstance(), s);
		} else {
			try {
				SimResultManager.getInstance().saveSimulation();
			} catch (Exception e1) {
				e1.printStackTrace();
			}
		}
	}
}