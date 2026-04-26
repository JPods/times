package com.instinct.gui.guactions;

import java.awt.Cursor;
import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.TimeGraph;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;
import com.instinct.service.TimeGraphMouseHandler;

public class ClearMapAction extends AbstractAction {
	public ClearMapAction() {
		super("Clear Route Time", GUIUtil.getImage("clean.png"));
		
		putValue(SHORT_DESCRIPTION, "Clear Route Time");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		TimeGraph.getInstance().setVisible(false,null);
		Pad.getInstance().removeMouseListener(TimeGraphMouseHandler.getInstance());
		Pad.getInstance().setCursor(new Cursor(Cursor.DEFAULT_CURSOR));

	}
}

