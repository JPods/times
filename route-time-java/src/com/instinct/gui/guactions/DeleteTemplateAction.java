package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.util.List;

import javax.swing.AbstractAction;
import javax.swing.JOptionPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.Toolbar;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.TemplateManager;
import com.instinct.service.WorkspaceManager;

public class DeleteTemplateAction extends AbstractAction {
	public DeleteTemplateAction() {
		super("Delete template...", GUIUtil.getImage("delete.png"));

		putValue(SHORT_DESCRIPTION, "Delete Template");
	}

	public void actionPerformed(ActionEvent e) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		String s = WorkspaceManager.getInstance().getValidationString();
		
		List<String> list = TemplateManager.getInstance().getTemplateList();
		if(list==null || list.size()==0) {
			JOptionPane.showMessageDialog(null,  "No template to delete");;
			return;
		}
		String[] array = list.toArray(new String[list.size()]);
	    String input = (String) JOptionPane.showInputDialog(null, "Choose","Template", JOptionPane.QUESTION_MESSAGE, null, array, array[0]); // Initial choice
	    TemplateManager.getInstance().deleteTemplate(input);
	    Toolbar.getInstance().updateToolbar();
	    
	}
}