package com.instinct.gui.pad;

import java.awt.Point;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.awt.event.MouseMotionListener;

import javax.swing.JPopupMenu;
import javax.swing.SwingUtilities;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.StationGlass;
import com.instinct.gui.TimeGraph;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.service.ActionManager;
import com.instinct.service.SimulationManager;
import com.instinct.service.WorkspaceManager;

public class PadController implements MouseMotionListener, MouseListener {

	
	private Pad pad;
	private DefaultMapController mapController = null;
	private SelectionManager selManager=SelectionManager.getInstance();
	
	public PadController(Pad pad) {
		mapController = new DefaultMapController(pad);
		this.pad = pad;
	}

	public void mouseClicked(MouseEvent me) {
		if(WorkspaceManager.getInstance().getNetwork()==null) {
			mapController.mouseClicked(me);
			return;
		}
		if(SimulationManager.getInstance().isSimulationRunning()) {
			doSimulationClick(me);
			return;
		}
		if (SwingUtilities.isRightMouseButton(me)) {
			doRightClickProcessing(me);
			return;
		} 
		
		
		
				
		boolean isConsumed=ActionManager.getInstance().consume(me.getPoint());
		if(isConsumed==false) {
			if(selManager.isSelecting()) {
				selManager.mouseClicked(me.getPoint());
				return;
			} else {
				mapController.mouseClicked(me);
			}
		}
	}
	

	private void doSimulationClick(MouseEvent me) {
		Drawable<?> h = pad.getHighligtableAt(me.getPoint());
		if(h==null) {
			return;
		}
		
		if((h.getModel() instanceof Station)==false) {
			return;
		}
		
		Station st=(Station)h.getModel();
		StationGlass sg=StationGlass.getInstance();
		sg.display();
		sg.setStationSelected(st);
	}

	private void doRightClickProcessing(MouseEvent me) {
		Drawable<?> h = pad.getHighligtableAt(me.getPoint());
		if (h == null) {
			return;
		}
		
		if(h.getModel() instanceof Node) {
			Node n=(Node)h.getModel();
			if(n.isNodeGroup()) {
				NodeGroup ng=n.getNodeGroup();
				JPopupMenu menu=ng.getPopupMenu();
				menu.show(Pad.getInstance(), me.getX(), me.getY());
				return;
			}
		}
		h.showEditor();
	}


	public void mouseEntered(MouseEvent me) {

	}

	public void mouseExited(MouseEvent me) {
	}

	public void mouseReleased(MouseEvent me) {
		if(WorkspaceManager.getInstance().getNetwork()==null) {
			mapController.mouseReleased(me);
			return;
		}
		if(Pad.getInstance().isGroupSelectEnabled()) {
			selectObjects();
			Pad.getInstance().setGroupSelect(false);
		}
		if (DragManager.getInstance().isDragInProgress()) {
			DragManager.getInstance().mouseReleased(me.getPoint());
		} else {
			mapController.mouseReleased(me);
		}
	}

	private void selectObjects() {
		Pad.getInstance().setCursorImage(null);
		for(Node node:WorkspaceManager.getInstance().getNetwork().getAllNodes()) {
			Point p=Pad.getInstance().getMapPosition(node.getLat(), node.getLon());
			if(Pad.getInstance().isWithinSelectedRectangle(p)) {
				SelectionManager.getInstance().addSelection(node);
			}
		}

		
	}

	public void mouseDragged(MouseEvent me) {
		if(WorkspaceManager.getInstance().getNetwork()==null) {
			dragMap(me);
			return;
		}
		if(Pad.getInstance().isGroupSelectEnabled()) {
			Pad.getInstance().setBottomRightGroupCorner(me.getPoint());
			return;
		}
		
		if (TimeGraph.getInstance().isVisible()) {
			dragMap(me);
			return;
		} 
		
		if(SimulationManager.getInstance().isSimulationRunning()) {
			dragMap(me);
			return;
		}
		
		if(DragManager.getInstance().drag(me.getPoint())==false) {
			dragMap(me);
			return;
		}
	}

	public void mousePressed(MouseEvent me) {
		if(WorkspaceManager.getInstance().getNetwork()==null) {
			return;
		}
		if(Pad.getInstance().isGroupSelectEnabled()) {
			Pad.getInstance().setTopLeftGroupCorner(me.getPoint());
		}
	}

	

	public void mouseMoved(MouseEvent me) {
		if(WorkspaceManager.getInstance().getNetwork()==null) {
			return;
		}
		Line line=WorkspaceManager.getInstance().getNetwork().getUncommitedLine();
		if(ActionManager.getInstance().isLineAddAction() && line==null) {
			Pad.getInstance().setGlow(null);
			Drawable<?> d=pad.getNearestNetworkNode(me.getPoint());
			if(d!=null && d.getModel() instanceof Switch) {
				Switch sw=(Switch)d.getModel();
				if(sw.getExitCount()<2) {
					Pad.getInstance().setGlow(d);
				}
			} 
			
		} else if(line!=null) {
			Switch  t1=(Switch) line.getEnd();
			if(t1!=null) {
				t1.detachEntryLine(line);
			}
			Switch t=new SwitchImpl("SW-1");
			Coordinate c=pad.getPosition(me.getPoint());
			t.setPosition(c);
			line.setEnd(t);
			t.attachEntryLine(line);
			if(line.isNetworkElement()) {
				Pad.getInstance().setGlowNetworked(line.getStart(),me.getPoint());
			} else {
				Pad.getInstance().setGlowNonNetworked(line.getStart(),me.getPoint());
				
			}
			pad.updateUI();
		} else if(ActionManager.getInstance().isMarkStationAction() && pad.getNodeAt(me.getPoint())!=null) {
			Node node=pad.getNodeAt(me.getPoint()).getModel();
			if(node !=null && node instanceof Station && node.isNodeGroup()==false && node.isComplete()==true) {
				Pad.getInstance().setGlowNetworked(null, me.getPoint());
			}
		} else if(ActionManager.getInstance().isFenceAddAction() && pad.getNodeAt(me.getPoint())!=null) {
			Node node=pad.getNodeAt(me.getPoint()).getModel();
			if(node !=null) {
				pad.showHandCursor();
			} else {
				pad.setCursorImage(null);
			}
		} else {
			if(pad.getNodeAt(me.getPoint())!=null && pad.isCustomCursorSet()==false && SimulationManager.getInstance().isSimulationRunning()==false) {
				pad.showHandCursor();
			} else if(pad.getNodeAt(me.getPoint())==null && pad.isHandCursor()==true) {
				pad.setCursorImage(null);
			}
		}
	}

	private void dragMap(MouseEvent me) {
		mapController.mouseDragged(me);
	}
	
	
}
