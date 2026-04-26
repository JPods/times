package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.RouteDisplay;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;

public class RoutesAction extends AbstractAction {
	public RoutesAction() {
		super("Routes", GUIUtil.getImage("route.png"));
		putValue(SHORT_DESCRIPTION, "Show routes");
		putValue(MNEMONIC_KEY, KeyEvent.VK_R);
		KeyBinder.getInstance().bind(KeyEvent.VK_R, this, "R");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		RouteDisplay display;
		try {
			display = new RouteDisplay();
			display.setVisible(true);
		} catch (Exception e) {
		}
	}
}
