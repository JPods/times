package com.instinct.gui.pad;

import java.awt.Cursor;
import java.awt.KeyEventDispatcher;
import java.awt.event.KeyEvent;

import com.instinct.gui.CostEstimateForm;
import com.instinct.gui.TimeGraph;
import com.instinct.gui.Toolbar;
import com.instinct.gui.property.CompositePropertyEditor;
import com.instinct.gui.property.FormBuilder;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.gui.tree.TemplatesPanel;
import com.instinct.service.ActionManager;
import com.instinct.service.TimeGraphMouseHandler;
import com.instinct.service.WorkspaceManager;
import com.instinct.service.actions.ObjectDeleteAction;

public class KeyController implements KeyEventDispatcher {

	@Override
	public boolean dispatchKeyEvent(KeyEvent e) {
		Pad pad = Pad.getInstance();
		if (e.getKeyCode() == KeyEvent.VK_DELETE  || e.getKeyCode() == KeyEvent.VK_K ) {
			ObjectDeleteAction a = new ObjectDeleteAction();
			if (a.validate(Pad.getInstance(), null, null)) {
				a.execute(null);
			}
		} else if (e.getKeyCode() == KeyEvent.VK_ESCAPE) {
			NodeGroupsPanel.getInstance().unselect();
			TemplatesPanel.getInstance().unselect();
			ActionManager.getInstance().setActionFactory(null);
			pad.setHighlight(null);
			pad.setDrawMergeLoad(false);
			if(TimeGraph.getInstance().isVisible()) {
				TimeGraph.getInstance().setVisible(false,null);
				Pad.getInstance().removeMouseListener(TimeGraphMouseHandler.getInstance());
				Pad.getInstance().setCursor(new Cursor(Cursor.DEFAULT_CURSOR));
			}
			Pad.getInstance().setCursorImage(null);
			Toolbar.getInstance().resetBtn();
		} else if (((e.getModifiers() & KeyEvent.CTRL_MASK) != 0) && (e.getID() == KeyEvent.KEY_RELEASED)) {
			if(e.getKeyCode() == KeyEvent.VK_Z) {
				ActionManager.getInstance().undo();
			}
						
		} else if (e.getKeyCode() == KeyEvent.VK_E && ((e.getModifiers() & KeyEvent.CTRL_MASK) != 0) && (e.getID() == KeyEvent.KEY_RELEASED)) {
			CostEstimateForm.getInstance().display();
		} else if (e.getKeyCode() == KeyEvent.VK_G && ((e.getModifiers() & KeyEvent.CTRL_MASK) != 0) && (e.getID() == KeyEvent.KEY_RELEASED)) {
			showGraphSettingsForm();
		} 
		pad.notifyComponents();
		return false;
	}

	private void showGraphSettingsForm() {
		CompositePropertyEditor editor = FormBuilder.getInstance().makeGraphSettingsForm(WorkspaceManager.getInstance().getWorkingSim());
		editor.setVisible(true);		
	}

}
