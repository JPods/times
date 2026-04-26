package com.instinct.gui.pad;

import java.awt.Point;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.StatusBar;
import com.instinct.gui.pad.widgets.CurveUI;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;

public class DragManager {

	private Node draggedNode;
	
	private Pad pad=Pad.getInstance();
	
	private Coordinate lastPosition=null;
	
	private static DragManager instance=new DragManager();
	
	public static DragManager getInstance() {
		return instance;
	}
	
	public void mouseReleased(Point p) {
		Node node = draggedNode;
		draggedNode=null;
		Pad.getInstance().updateUI();
	}
	
	public boolean isDragInProgress() {
		return draggedNode!=null;
	}
	
	public boolean drag(Point p) {
		Drawable d=pad.getNodeAt(p);
		boolean ret=false;
		if (d instanceof CurveUI) {
			tryDraggingLine(p);
			ret= true;
		} else {
			ret= tryDraggingNode(p);
		}
		StatusBar.getInstance().updateDesignMode();
		return ret;
	}


	private void tryDraggingLine(Point p) {
		Drawable d=pad.getNodeAt(p);
		CurveUI cui = (CurveUI)d;
		cui.getModel().drag(p);
		pad.updateUI();
	}

	private boolean tryDraggingNode(Point p) {
		if (draggedNode != null) {
			Coordinate cord = pad.getPosition(p);
			Coordinate delta=new Coordinate(cord.getLat()-draggedNode.getLat(), cord.getLon()-draggedNode.getLon());
			if(SelectionManager.getInstance().isSelecting()) {
				SelectionManager.getInstance().moveSelection(delta);
				return true;
			} else if (draggedNode.isNodeGroup()) {
				draggedNode.getNodeGroup().move(delta);
			} else {
				draggedNode.move(delta);
			}
			pad.updateUI();
		} else {
			Drawable<? extends Node> startNode = pad.getNodeAt(p);
			if (startNode != null) {
				draggedNode=startNode.getModel();
			} else {
				return false;
			}
		}
		return true;
	}

	
}
