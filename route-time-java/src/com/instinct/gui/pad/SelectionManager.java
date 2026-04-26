package com.instinct.gui.pad;

import java.awt.KeyEventDispatcher;
import java.awt.Point;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.gui.tree.TemplatesPanel;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.RenderableObject;
import com.instinct.service.ActionManager;
import com.instinct.service.WorkspaceManager;

public class SelectionManager implements KeyEventDispatcher {

	private boolean isSelecting=false;
	
	private static SelectionManager instance=new SelectionManager();
	
	private Map<String, NodeGroup> selectedNodeGroups=new HashMap<String, NodeGroup>();
	
	private Map<String, Line> selectedLines=new HashMap<String, Line>();
	
	private Map<String, Node> selectedNodes=new HashMap<String, Node>();

	
	public static SelectionManager getInstance() {
		return instance;
	}
	
	private SelectionManager() {
	}
	
	

	public void mouseClicked(Point p) {
		
		Drawable<?> d=Pad.getInstance().getNodeAt(p);
	    
		if(d==null || (d.getModel() instanceof Node)==false) {
			trySelectLine(p);
			return;
		}
		
		Node n=(Node)d.getModel();
		addSelection(n);
	}
	
	private void trySelectLine(Point p) {
		Drawable<?> d =Pad.getInstance().getLineAt(p);
		if(d==null) {
			return;
		}
		
		Line line=(Line)d.getModel();
		
		if(line.getStart().isNodeGroup() && line.getEnd().isNodeGroup() && line.getStart().getNodeGroup().getId().equals(line.getEnd().getNodeGroup().getId())) {
			addSelection(line.getEnd());
		} else {
			d.setHighlight(true);
			selectedLines.put(line.getId(), line);
		}
		
	}

	public void addSelection(Node n) {
		if(n.isNodeGroup()) {
			selectedNodeGroups.put(n.getNodeGroup().getId(), n.getNodeGroup());
			for(Node n1:n.getNodeGroup().getNodes()) {
				((RenderableObject<?>)n1).getUI().setHighlight(true);
			}
		} else {
			selectedNodes.put(n.getId(), n);
			((RenderableObject<?>)n).getUI().setHighlight(true);

		}
	}


	public boolean isSelecting() {
		return isSelecting;
	}

	@Override
	public boolean dispatchKeyEvent(KeyEvent evt) {
		
		if(evt.getModifiers() == InputEvent.CTRL_MASK && evt.getID() == KeyEvent.KEY_PRESSED) {
			isSelecting=true;
			Pad.getInstance().showAlertIndefinte("Selection Mode is On");
			ActionManager.getInstance().setActionFactory(null);
			Pad.getInstance().setCursorImage(null);
			TemplatesPanel.getInstance().unselect();
		} else if(evt.getKeyCode() == KeyEvent.VK_ESCAPE)  {
			if(isSelecting) {
				Pad.getInstance().showAlert("Selection Mode is Off");
			}
			reset();
		} else if(evt.getKeyCode() == KeyEvent.VK_F2 && evt.getID() == KeyEvent.KEY_RELEASED) {
			//TODO paste();
		} 
		return false;
	}

	public void reset() {
		if(isSelecting) {
			Pad.getInstance().showAlert("Selection Mode is Off");
		}
		isSelecting=false;
		for(Line l:selectedLines.values()) {
			l.getUI().setHighlight(false);
		}
		
		for(NodeGroup ng:selectedNodeGroups.values()) {
			for(Node n:ng.getNodes()) {
				((RenderableObject<?>)n).getUI().setHighlight(false);
			}
		}
		for(Node n:selectedNodes.values()) {
			((RenderableObject<?>)n).getUI().setHighlight(false);
		}
		selectedNodes.clear();
		selectedNodeGroups.clear();

	}

	private void paste() {
	}

	public Collection<Line> getLines() {
		return selectedLines.values();
	}

	public void setSelecting(boolean b) {
		this.isSelecting=b;
	}

	public void deleteSelection() {
		for(Line ln:SelectionManager.getInstance().getLines())  {
			ln.remove();
		}
		
		for(Node n:selectedNodes.values()) {
			n.remove();
		}

		for(NodeGroup ng:selectedNodeGroups.values()) {
			for(Node n:ng.getNodes()) {
				n.removeWithinNodeGroup();
				n.remove();
			}
			ng.removeGroup();
			WorkspaceManager.getInstance().getNetwork().removeGroup(ng.getId());
		}
		NodeGroupsPanel.getInstance().updateGroups();
		Pad.getInstance().updateUI();
	}

	public void moveSelection(Coordinate delta) {
		for(NodeGroup ng:selectedNodeGroups.values()) {
			ng.move(delta);
		}
		for(Node n:selectedNodes.values()) {
			n.move(delta);
		}
	}

	private Coordinate getCenter() {
		int i=0;
		double totalLat=0, totalLon=0;
		for(NodeGroup ng:selectedNodeGroups.values()) {
			for(Node n:ng.getNodes()) {
				totalLat=totalLat+n.getLat();
				totalLon=totalLon+n.getLon();
				i++;
			}
		}
		for(Node n:selectedNodes.values()) {
			totalLat=totalLat+n.getLat();
			totalLon=totalLon+n.getLon();
			i++;
		}

		return new Coordinate(totalLat/i, totalLon/i);
	}

}
