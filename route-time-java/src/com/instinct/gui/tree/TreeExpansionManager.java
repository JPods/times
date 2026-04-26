package com.instinct.gui.tree;

import javax.swing.event.TreeExpansionEvent;
import javax.swing.event.TreeExpansionListener;
import javax.swing.tree.DefaultMutableTreeNode;

public class TreeExpansionManager implements TreeExpansionListener {

	private boolean isLinesExpanded, isSwitchesExpanded, isStationsExpanded, isSimulationsExpanded;
	
	@Override
	public void treeCollapsed(TreeExpansionEvent e) {
		DefaultMutableTreeNode node=(DefaultMutableTreeNode)e.getPath().getLastPathComponent();
		if(node.getUserObject().equals("Stations")) {
			isStationsExpanded=false;
		} if(node.getUserObject().equals("Lines")) {
			isLinesExpanded=false;
		} if(node.getUserObject().equals("Switches")) {
			isSwitchesExpanded=false;
		} if(node.getUserObject().equals("Simulations")) {
			isSimulationsExpanded=false;
		} 
	}

	@Override
	public void treeExpanded(TreeExpansionEvent e) {
		DefaultMutableTreeNode node=(DefaultMutableTreeNode)e.getPath().getLastPathComponent();
		if(node.getUserObject().equals("Stations")) {
			isStationsExpanded=true;
		} if(node.getUserObject().equals("Lines")) {
			isLinesExpanded=true;
		} if(node.getUserObject().equals("Switches")) {
			isSwitchesExpanded=true;
		} if(node.getUserObject().equals("Simulations")) {
			isSimulationsExpanded=true;
		} 
	}

	public boolean isLinesExpanded() {
		return isLinesExpanded;
	}

	public boolean isSwitchesExpanded() {
		return isSwitchesExpanded;
	}

	public boolean isStationsExpanded() {
		return isStationsExpanded;
	}

	public boolean isSimulationsExpanded() {
		return isSimulationsExpanded;
	}
}
