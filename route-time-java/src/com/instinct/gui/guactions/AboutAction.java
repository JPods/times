package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.AboutDisplay;
import com.instinct.gui.GUIUtil;

public class AboutAction extends AbstractAction {
	
	public AboutAction() {
		super("", GUIUtil.getImage("about.png"));
		putValue(SHORT_DESCRIPTION, "About Us");
	}

	public void actionPerformed(ActionEvent ae) {
		AboutDisplay ad=new AboutDisplay();
		ad.setVisible(true);
		
	}
}



