package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;

import javax.swing.AbstractAction;
import javax.swing.JButton;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.SimulationManager;

public class StartStopSimAction extends AbstractAction {
	public StartStopSimAction() {
		super("Start", GUIUtil.getImage("start.png"));

		putValue(SHORT_DESCRIPTION, "Start Simulation");
		putValue(MNEMONIC_KEY, KeyEvent.VK_I);
		KeyBinder.getInstance().bind(KeyEvent.VK_I, this, "I");

	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		if(SimulationManager.getInstance().checkIfSaved()==false) {
			return;
		}

		JButton startStopSimBtn = (JButton) e.getSource();
		if (startStopSimBtn.getText().equals("Start")) {
			startStopSimBtn.setText("Stop");
			startStopSimBtn.setIcon(GUIUtil.getImage("stop.png"));
			SimulationManager.getInstance().startSimulation();
		} else {
			startStopSimBtn.setIcon(GUIUtil.getImage("start.png"));
			startStopSimBtn.setText("Start");
			SimulationManager.getInstance().stopSimulation();
		}
		try {
			Thread.sleep(500);
		} catch (InterruptedException e1) {
			e1.printStackTrace();
		}

	}

}
