package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class MarkStationAction extends AbstractAction {
	public MarkStationAction() {
		super("Mark Station", GUIUtil.getImage("mark-station.png"));
		putValue(SHORT_DESCRIPTION, "Mark Station");
		putValue(MNEMONIC_KEY, KeyEvent.VK_M);
		KeyBinder.getInstance().bind(KeyEvent.VK_M, this, "M");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("mark-station.png");

		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getStationMarkFac());
	}
}




