package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;

import javax.swing.AbstractAction;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.ActionManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class AddTemplateAction extends AbstractAction {
	private String template;

	public AddTemplateAction(String t) {
		super(t, GUIUtil.getImage("template.png"));
		this.template=t;
		putValue(SHORT_DESCRIPTION, "Add Template");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage("template.png");

		
		ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getTemplateAddFac(template));
	}
}

