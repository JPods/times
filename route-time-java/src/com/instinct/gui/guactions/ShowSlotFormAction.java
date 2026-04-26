package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.SlotForm;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;

public class ShowSlotFormAction extends AbstractAction {
	public ShowSlotFormAction() {
		super("Slots", GUIUtil.getImage("passenger.png"));
		
		putValue(SHORT_DESCRIPTION, "Show Pasenger destinations for each time slot");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		SlotForm.getInstance().display();
	}
}
