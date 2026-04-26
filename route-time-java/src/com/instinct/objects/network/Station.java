package com.instinct.objects.network;

import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.geom.Point2D;
import java.util.LinkedList;
import java.util.Queue;
import java.util.concurrent.atomic.AtomicInteger;

import javax.swing.JMenuItem;
import javax.swing.JPopupMenu;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.config.Config;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.gui.pad.widgets.StationUI;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.objects.Passenger;
import com.instinct.objects.pod.Pod;
import com.instinct.service.WorkspaceManager;

public class Station implements RenderableObject<Station>, PodQueueHolder, PassengerQueueHolder, Node {

	private static AtomicInteger idGen = new AtomicInteger(0);
	private static final long serialVersionUID = 1L;

	private String displayName;
	private Line entry;
	private Line exit;
	private final String id;
	private double lat, lon;
	private NodeGroup nodeGrp;
	private Queue<Passenger> passengerQueue = new LinkedList<Passenger>();
	private PodQueue podQueue = new PodQueue(4);
	private StationUI ui;
	private int RESERVED_POD=75;

	private AtomicInteger podsExpended=new AtomicInteger(0);
	private JPopupMenu popup;
	
	public Station clone() {
		Station clone=new Station();
		clone.lat=this.lat;
		clone.lon=this.lon;
		return clone;
	}

	public void callPodFromDepot() {
		if(podsExpended.get()>=RESERVED_POD) {
			return;
		}
		Pod pod = new Pod();
		podQueue.addPod(pod);
		putPodsOnLine();
		podsExpended.incrementAndGet();
	}
	
	public void returnPodToDepot() {
		if(podsExpended.get()>0) {
			podsExpended.decrementAndGet();
		}
		getPodQueue().removePod();
		getEntry().getPodQueue().removePod();
	}
	
	public Station() {
		this("ST" + idGen.getAndIncrement());
	}

	public Station(String id) {
		this.id = id;
		Point2D p = new Point2D.Double(0, 0);
		ui = new StationUI(p, this);
		buildMenu();
	}

	public void addPassenger(Passenger passenger) {
		if (passengerQueue == null) {
			passengerQueue = new LinkedList<Passenger>();
		}
		if (passengerQueue.size() < 100) {
			passengerQueue.add(passenger);
		}
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (!(obj instanceof Node))
			return false;
		return id.equals(((Node) obj).getId());
	}

	public void putPassengersToPods(int time) {
		if (getPassengerQueue().size() > 0) {
			putPassengerToPod(time);
		}
	}

	public Line getEntry() {
		return entry;
	}

	public Line getExit() {
		return exit;
	}

	@Override
	public String getId() {
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

	public String getName() {
		return displayName;
	}

	@Override
	public NodeGroup getNodeGroup() {
		return nodeGrp;
	}

	public Queue<Passenger> getPassengerQueue() {
		return passengerQueue;
	}

	public PodQueue getPodQueue() {
		return podQueue;
	}

	@Override
	public Drawable<Station> getUI() {
		return ui;
	}

	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((id == null) ? 0 : id.hashCode());
		return result;
	}

	public synchronized void initPodQueue() {
		int podsPerStation = WorkspaceManager.getInstance().getWorkingSim().getSettings().getPodsPerStation();
		podQueue = new PodQueue(podsPerStation);
		for (int i = 0; i < podsPerStation; i++) {
			Pod pod = new Pod();
			podQueue.addPod(pod);
		}
		putPodsOnLine();
	}

	public boolean isComplete() {
		return entry != null && exit != null;
	}

	public boolean isEntry(Line line) {
		if (entry.getId().equals(line.getId())) {
			return true;
		}
		return false;
	}

	public boolean isExit(Line line) {
		if (exit.getId().equals(line.getId())) {
			return true;
		}
		return false;
	}

	@Override
	public boolean isNodeGroup() {
		return nodeGrp != null;
	}

	private synchronized void putPassengerToPod(int startTime) {
		Passenger passenger = passengerQueue.peek();
		Pod pod = getPodQueue().getHeadPod();

		if (passenger == null) {
			return;
		}
		
		pod = getPodQueue().getHeadPod();
		if(pod==null) {
			return;
		}
		podQueue.removePod();
		passengerQueue.remove();
		pod.loadPod(passenger);
		passenger.setMovementStartTime(startTime);
		WorkspaceManager.getInstance().getWorkingSim().getSummary().logPassengerStartMoving(passenger);
	}

	

	@Override
	public void remove() {
		if (entry != null && entry.getStart() != null) {
			Switch s1 = (Switch) entry.getStart();
			s1.detachExitLine(entry);
			s1.removeWithinNodeGroup();
			s1.remove();
		}

		if (exit != null && exit.getEnd() != null) {
			Switch s2 = (Switch) exit.getEnd();
			s2.detachEntryLine(exit);
			s2.removeWithinNodeGroup();
			s2.remove();
		}

		WorkspaceManager.getInstance().getNetwork().removeLine(entry);
		WorkspaceManager.getInstance().getNetwork().removeLine(exit);
		WorkspaceManager.getInstance().getNetwork().removeNode(this);
	}

	public void removeLine(String lineId) {
		if (entry != null && entry.getId().equals(lineId)) {
			entry = null;
		}
		if (exit != null && exit.getId().equals(lineId)) {
			exit = null;
		}
	}

	@Override
	public void removeWithinNodeGroup() {
		remove();
	}

	public void setEntry(Line entry) {
		this.entry = entry;
	}

	public void setExit(Line exit) {
		this.exit = exit;
	}

	public void setName(String displayName) {
		this.displayName = displayName;
	}

	@Override
	public void setNodeGroup(NodeGroup nodeGrp) {
		this.nodeGrp = nodeGrp;
	}

	@Override
	public void setPosition(Coordinate n) {
		setPosition(n.getLat(), n.getLon());
	}

	@Override
	public void setPosition(double lat, double lon) {
		this.lat = lat;
		this.lon = lon;
	}

	@Override
	public void setPosition(Node n) {
		setPosition(n.getLat(), n.getLon());

	}

	@Override
	public String toString() {
		return displayName == null ? id : displayName;
	}

	public void updateLineLengths() {
		if (entry != null) {
			this.entry.recomputeLength();
		}
		if (exit != null) {
			this.exit.recomputeLength();
		}
	}

	public static int getLastId() {
		return idGen.get();
	}

	public static void setLastId(int lastId) {
		idGen.set(lastId + 1);
	}

	private void putPodsOnLine() {
		if (entry == null) {
			return;
		}
		double distance = entry.getLength();
		for (Pod pod : podQueue.getAll()) {
			distance = distance - Config.getInstance().getPodSpace();
			pod.setDistanceSinceLastNode(distance);
			pod.setCurrentLine(entry, 0);
			entry.getPodQueue().addPod(pod);
		}

	}

	private void buildMenu() {
		popup = new JPopupMenu();
		final Station self=this;
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

	public void resetPodDepot() {
		podsExpended.set(0);
		
	}
	
	public int getPodExpended() {
		return podsExpended.get();
	}

	@Override
	public void move(Coordinate c) {
		this.lat=this.lat+c.getLat();
		this.lon=this.lon+c.getLon();
		
	}
	
	

}
