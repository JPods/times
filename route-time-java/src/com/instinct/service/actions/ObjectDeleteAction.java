package com.instinct.service.actions;

import java.awt.Point;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.service.WorkspaceManager;

public class ObjectDeleteAction implements Action {

	@Override
	public Object execute(Point p) {
		SelectionManager.getInstance().deleteSelection();
		NodeGroupsPanel.getInstance().updateGroups();
		return null;
	}


	@Override
	public void undo() {
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		return true;
	}

	@Override
	public void init(Point p) {
	}

	@Override
	public boolean isDone() {
		return true;
	}

	@Override
	public void abort() {
	}

}
