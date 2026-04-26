package com.instinct.objects.network;

import java.awt.Point;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.concurrent.atomic.AtomicInteger;

import javax.swing.JMenuItem;
import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.pad.widgets.SwitchUI;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.service.WorkspaceManager;

public class SwitchImpl implements Switch, RenderableObject<Switch>, Cloneable {



	private Line entry1, entry2, exit1, exit2;

	private double lat, lon;

	private String id;

	private NodeGroup ng;

	private SwitchUI ui;
	
	private boolean isNetworklElement=true;

	private JPopupMenu popup;
	
	private TrafficCircle trafficCircleIfPartOf;

	public TrafficCircle getTrafficCircleIfPartOf() {
		return trafficCircleIfPartOf;
	}

	public void setTrafficCircleIfPartOf(TrafficCircle trafficCircleIfPartOf) {
		this.trafficCircleIfPartOf = trafficCircleIfPartOf;
	}

	private static AtomicInteger idGen = new AtomicInteger(0);

	public SwitchImpl(String id) {
		this.id=id;
		ui = new SwitchUI(new Point(0, 0), this);
		buildMenu();
	}
	
	public void internalize(NodeGroup ng, Line entry1, Line exit1, Line entry2, Line exit2)  {
		this.entry1=entry1;
		this.exit1=exit1;
		this.entry2=entry2;
		this.exit2=exit2;
		this.ng=ng;
	}
	
 	
	public SwitchImpl() {
		this(0, 0);
	}

    public SwitchImpl(double lat, double lon) {
		id = "SW" + idGen.getAndIncrement();
		this.lat = lat;
		this.lon = lon;
		ui = new SwitchUI(new Point(0, 0), this);
		buildMenu();
	}
    
    public SwitchImpl clone() {
    	SwitchImpl clone=new SwitchImpl();
		clone.lat=this.lat;
		clone.lon=this.lon;
		return clone;
    }
	
	@Override
	public String toString() {
		return id;
	}

	@Override
	public double getLat() {
		return lat;
	}

	@Override
	public double getLon() {
		return lon;
	}

	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((id == null) ? 0 : id.hashCode());
		return result;
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (getClass() != obj.getClass())
			return false;
		SwitchImpl other = (SwitchImpl) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}

	@Override
	public String getId() {
		return id;
	}

	@Override
	public void setPosition(double lat, double lon) {
		this.lat = lat;
		this.lon = lon;

	}

	@Override
	public void setPosition(Node n) {
		this.lat = n.getLat();
		this.lon = n.getLon();

	}

	@Override
	public void setPosition(Coordinate c) {
		this.lat = c.getLat();
		this.lon = c.getLon();

	}

	@Override
	public void updateLineLengths() {
		updateLineLength(entry1);
		updateLineLength(entry2);
		updateLineLength(exit1);
		updateLineLength(exit2);
	}
	
	private void updateLineLength(Line line) {
		if(line!=null) {
			line.recomputeLength();
		}
	}

	@Override
	public String getName() {
		return id;
	}

	

	@Override
	public NodeGroup getNodeGroup() {
		return ng;
	}

	@Override
	public void setNodeGroup(NodeGroup nodeGrp) {
		ng = nodeGrp;

	}

	@Override
	public boolean isNodeGroup() {
		return ng != null;
	}

	@Override
	public void remove() {
		removeLine(entry1);
		removeLine(entry2);
		removeLine(exit1);
		removeLine(exit2);
		if(isNetworklElement) {
		WorkspaceManager.getInstance().getNetwork().removeNode(this);
		} else {
			WorkspaceManager.getInstance().getNetwork().removeBoundaryNode(this);
		}
	}
	
	private void removeLine(Line line) {
		if(line!=null) {
			line.remove();
		}
	}

	@Override
	public void attachEntryLine(Line line) {
		if (entry1 == null) {
			entry1 = line;
		} else {
			entry2 = line;
		}
	}

	@Override
	public void detachEntryLine(Line line) {
		if (entry1 != null && entry1.equals(line)) {
			entry1 = null;
		} else if (entry2 != null && entry2.equals(line)) {
			entry2 = null;
		}
	}

	@Override
	public void attachExitLine(Line line) {
		if (exit1 == null) {
			exit1 = line;
		} else {
			exit2 = line;
		}
	}

	@Override
	public void detachExitLine(Line line) {
		if (exit1 != null && exit1.equals(line)) {
			exit1 = null;
		} else if(exit2 != null && exit2.equals(line)) {
			exit2 = null;
		}
	}

	@Override
	public int getEntryCount() {
		int ret=0;
		if(entry1!=null) {
			ret=ret+1;
		}
		if(entry2!=null) {
			ret=ret+1;
		}
		return ret;
	}

	@Override
	public int getExitCount() {
		int ret=0;
		if(exit1!=null) {
			ret=ret+1;
		}
		if(exit2!=null) {
			ret=ret+1;
		}
		return ret;
	}

	

	@Override
	public Line getEntry1() {
		return entry1;
	}

	@Override
	public Line getExit1() {
		return exit1;
	}

	@Override
	public Line getEntry2() {
		return entry2;
	}

	@Override
	public Line getExit2() {
		return exit2;
	}

	@Override
	public Line getEntry() {
		return entry1 != null ? entry1 : entry2;
	}

	@Override
	public Line getExit() {
		return exit1 != null ? exit1 : exit2;
	}

	@Override
	public Line getOtherEntry(Line line) {
		if ((entry1 != null && entry1.equals(line))) {
			return entry2;
		} else if ((entry2 != null && entry2.equals(line))) {
			return entry1;
		} else {
			return null;
		}
	}

	@Override
	public Line getOtherExit(Line line) {
		if ((exit1 != null && exit1.equals(line))) {
			return exit2;
		} else if ((exit2 != null && exit2.equals(line))) {
			return exit1;
		} else {
			return null;
		}
	}

	
	@Override
	public Drawable<Switch> getUI() {
		return ui;
	}

	@Override
	public void removeWithinNodeGroup() {
		removeLineWithinNodeGrp(entry1);
		removeLineWithinNodeGrp(entry2);
		removeLineWithinNodeGrp(exit1);
		removeLineWithinNodeGrp(exit2);
		WorkspaceManager.getInstance().getNetwork().removeNode(this);
	}
	
	private void removeLineWithinNodeGrp(Line line) {
		if(line!=null) {
			line.removeWithinNodeGroup();
		}
	}

	public static int getLastId() {
		return idGen.get();
	}

	public static void setLastId(int lastId) {
		idGen.set(lastId+1);
	}
	
	@Override
	public boolean isComplete() {
		if((getExitCount()==2 && getEntryCount()==1) || (getEntryCount()==2 && getExitCount()==1)) {
			return true;
		}
		return false;
	}
	
	public boolean checkValidEntry() {
		if(isComplete()) {
			return false;
		}
		
		if(getEntryCount()==2) {
			return false; 
		}
		return true;
	}
	
	public boolean checkValidExit() {
		if(isComplete()) {
			return false;
		}
		
		if(getExitCount()==2) {
			return false; 
		}
		return true;
	}

	@Override
	public boolean isNetworkElement() {
		return isNetworklElement;
	}

	@Override
	public void setNetworkElement(boolean isNetworkElement) {
		this.isNetworklElement=isNetworkElement;
	}
	
	private void buildMenu() {
		popup = new JPopupMenu();
		final SwitchImpl self=this;
		ActionListener aListener=new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				if(ae.getActionCommand().equals("Delete")) {
					self.remove();
					Pad.getInstance().updateUI();
					NetworkTree.getInstance().updateTree();
				}
			}
			
		};
		JMenuItem item;
	    popup.add(item = new JMenuItem("Delete"));
	    item.addActionListener(aListener);

	}

	@Override
	public JPopupMenu getPopupMenu() {
		return popup;
	}

	@Override
	public void move(Coordinate c) {
		this.lat=this.lat+c.getLat();
		this.lon=this.lon+c.getLon();
	}
}
