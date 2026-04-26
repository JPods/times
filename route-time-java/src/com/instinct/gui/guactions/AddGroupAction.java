package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;

public class AddGroupAction extends AbstractAction {
	public AddGroupAction() {
		super("Group", GUIUtil.getImage("rectangle.png"));
		putValue(SHORT_DESCRIPTION, "Group Objects");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("rectangle.png");
		Pad.getInstance().setGroupSelect(true);
		SelectionManager.getInstance().setSelecting(true);
	}
}




