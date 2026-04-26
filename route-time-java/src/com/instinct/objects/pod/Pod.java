package com.instinct.objects.pod;

import java.io.Serializable;
import java.util.concurrent.atomic.AtomicInteger;

import com.instinct.config.Config;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.Passenger;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.network.SwitchImpl;
import com.instinct.objects.network.TrafficCircle;
import com.instinct.objects.simulation.SimulationSettings;
import com.instinct.objects.simulation.event.SimEvent;
import com.instinct.service.FixedSizeQueue;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.LoopDetector;
import com.instinct.service.RouteTableService;
import com.instinct.service.WorkspaceManager;

public class Pod implements Serializable {

	private transient int startTime = 0, lastUpdatedTime = 0;
	private Line currentLine;
	private Node lastNode;
	private Throttle throttle = Throttle.BREAK;
	private double distanceSinceLastNode = 0;
	private double velocity = 0;
	private Passenger passenger;
	private FixedSizeQueue<SimEvent> history = new FixedSizeQueue<SimEvent>(50);
	private String id = "P" + idGen.getAndIncrement();
	private SimulationSettings cfg;

	private boolean isGlow = false;
	private boolean mergeLock = false;
	private boolean isCrashed = false;
	
	private static AtomicInteger idGen = new AtomicInteger(0);
	
	private static AtomicInteger crashCount = new AtomicInteger(0);
	
	private LoopDetector loopDetector=new LoopDetector();
	
	public Pod() {
		
	}
	
	public int getLastUpdatedTime() {
		return lastUpdatedTime;
	}

	public boolean isGlow() {
		return isGlow;
	}

	public void setGlow(boolean isGlow) {
		this.isGlow = isGlow;
	}

	public void setLastUpdatedTime(int lastUpdatedTime) {
		this.lastUpdatedTime = lastUpdatedTime;
	}

	public FixedSizeQueue<SimEvent> getEvents() {
		return history;
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
		Pod other = (Pod) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}

	public synchronized int getStartTime() {
		return startTime;
	}

	public synchronized void setStartTime(int startTime) {
		this.startTime = startTime;
	}

	public boolean isWithinBayArea() {
		Station st = (Station) currentLine.getEnd();
		double gap = currentLine.getLength() - this.distanceSinceLastNode;
		double bayLength = st.getPodQueue().getCapacity() * Config.getInstance().getPodSpace();
		if (bayLength > gap) {
			return true;
		}
		return false;

	}

	public Pod getConvergingPod() {
		Switch sw = (Switch) currentLine.getEnd();
		Line otherLine = sw.getOtherEntry(currentLine);
		if (otherLine == null) {
			return null;
		}
		Pod otherPod = otherLine.getPodQueue().getHeadPod();

		return otherPod;
	}

	public void changePos(int time) {
		this.cfg = WorkspaceManager.getInstance().getWorkingSim().getSettings();
		double deltaPos = getDisplacementAndSetNewVelocity();
		checkForCrash(time, deltaPos);
		if (!willCrossLineForThisChangeInPos(deltaPos)) {
			this.setDistanceSinceLastNode(this.getDistanceSinceLastNode() + deltaPos);
		} else {
			changeLine(deltaPos, time);
		}
		this.getPassenger().addDistanceTraveled(deltaPos);
	}

	private void checkForCrash(int time, double deltaPos) {
		Pod podAhead = currentLine.getPodQueue().getPodAhead(this);
		if (podAhead == null || deltaPos<=0.0) {
			return;
		}
		double gap = podAhead.getDistanceSinceLastNode() - this.getDistanceSinceLastNode();
		if (gap<deltaPos) {
			//System.out.println(crashCount.incrementAndGet());
			//printDiagnosticsAndHalt(time, deltaPos, podAhead, gap);
		}
	}

	// v^2/2a
	public double getStoppingDistance() {
		return getStoppingDistance(this.velocity);
	}

	public double getStoppingDistance(double velocity) {
		if (velocity < 0) {
			return 0;
		}
		double a = WorkspaceManager.getInstance().getWorkingSim().getSettings().getDeccInTU();

		return (velocity * velocity) / (2 * a);
	}

	private double getDisplacementAndSetNewVelocity() {
		double s = getDisplacement();
		velocity = getVelocityChange();
		return s;
	}

	private double getVelocityChange() {
		double change;
		if (this.throttle == Throttle.BREAK) {
			change = velocity - cfg.getDeccInTU();
		} else if (this.throttle == Throttle.ACCELERATE) {
			change = velocity + cfg.getAccInTU();
		} else {
			change = 0;
		}
		if (change > cfg.getMaxVelocityInTU()) {
			change = cfg.getMaxVelocityInTU();
		} else if (change < 0) {
			change = 0;
		}

		return change;
	}

	private double getDisplacement() {
		double s = 0.0;
		if (Throttle.BREAK == throttle) {
			s = velocity - 0.5 * cfg.getDeccInTU();
			s = s < 0 ? 0 : s;
		} else if (Throttle.ACCELERATE == throttle) {
			s = velocity + 0.5 * cfg.getAccInTU();
			s = s > cfg.getMaxVelocityInTU() ? cfg.getMaxVelocityInTU() : s;
		}
		return s;
	}

	private boolean willCrossLineForThisChangeInPos(double deltaPos) {
		if (currentLine.getEnd().getId().equals(getDestinationNode().getId())) {
			return false;
		}
		double gap = currentLine.getLength() - getDistanceSinceLastNode();

		return deltaPos > gap;
	}

	private synchronized void changeLine(double delta, int time) {
		double gap = getCurrentLine().getLength() - getDistanceSinceLastNode();
		delta = delta - gap;
		Line nextLine = getNextLineAfterCrossing();
		currentLine.getPodQueue().removePod();
		setLastNode(currentLine.getEnd());
		nextLine.getPodQueue().addPod(this);
		setCurrentLine(nextLine, time);
		setDistanceSinceLastNode(delta);
		this.mergeLock = false;
	}

	public Node getDestinationNode() {
		return passenger.getEnd();
	}

	public void stepGasIfSpeedIsLow() {
		if (velocity < cfg.getMaxVelocityInTU()) {
			stepGas();
		}
	}

	public boolean isOnLastLine() {
		return currentLine.getEnd().equals(this.getDestinationNode());
	}

	public synchronized Line getCurrentLine() {
		return currentLine;
	}

	public synchronized void setCurrentLine(Line currentLine, int time) {
		this.currentLine = currentLine;
	}

	public synchronized Node getLastNode() {
		return lastNode;
	}

	public synchronized void setLastNode(Node lastNode) {
		this.lastNode = lastNode;
	}

	public synchronized Throttle getThrottle() {
		return throttle;
	}

	public void setId(String id) {
		this.id = id;
	}

	public synchronized double getDistanceSinceLastNode() {
		return distanceSinceLastNode;
	}

	public synchronized void setDistanceSinceLastNode(double distanceSinceLastNode) {
		this.distanceSinceLastNode = distanceSinceLastNode;
	}

	public boolean isParked() {
		return passenger == null;
	}

	public synchronized void loadPod(Passenger passenger) {
		Node start = passenger.getStart();
		this.setLastNode(start);
		this.passenger = passenger;
		this.cfg = WorkspaceManager.getInstance().getWorkingSim().getSettings();
	}

	public void setThrottle(Throttle throttle) {
		this.throttle = throttle;
	}

	public void setVelocity(double velocity) {
		this.velocity = velocity;
	}

	public String getId() {
		return id;
	}

	public Line getNextLine() {
		Node node = currentLine.getEnd();
		if (node instanceof Station) {
			return null;
		}
		SwitchImpl sw = (SwitchImpl) node;
		if (sw.getExitCount() == 1) {
			return sw.getExit();
		} else {
			if(sw.getExit1().isJammed()) {
				return sw.getExit2();
			} else if(sw.getExit2().isJammed()) {
				return sw.getExit1();
			}
			return getNextLineAfterCrossing();
		}
	}
	

	private Line getNextLineAfterCrossing() {
		Node crossing=currentLine.getEnd();
		Node nextNode = RouteTableService.getInstance().getNextNode(crossing, getDestinationNode());
		

		if(nextNode instanceof Station) {
			if(!passenger.getEnd().getId().equals(nextNode.getId())) {
				Station st=(Station)nextNode;
				nextNode=st.getExit().getEnd();
			} else { //by passing destination because of over-crowded pods
				Station st=(Station)nextNode;
				if(st.getEntry().getPodQueue().size()>4) {
					nextNode=st.getExit().getEnd();
				}
			}
		}
		
		Line nextLine = WorkspaceManager.getInstance().getNetwork().getLine(crossing, nextNode);
		loopDetector.offerLine(nextLine);
		if((nextLine.isJammed() || isNext2LinesJammed(nextLine) || loopDetector.isOnLoop()) && crossing instanceof Switch) {
			Switch sw=(Switch)crossing;
			if(sw.getExitCount()==2) {
				Line tLine=sw.getOtherExit(nextLine);
				if((tLine.getEnd() instanceof Station)==false) {
					if(tLine.getTailGap()>20) {
						nextLine=tLine;
						loopDetector.reset();
					}
				}
			}
		} 
		return nextLine;
	}

	private boolean isNext2LinesJammed(Line line) {
		Line nextLine=getNextLine(line);
		if(nextLine==null) {
			return false;
		}
		
		if(nextLine.isJammed()) {
			return true;
		}
		Line nextToNextLine=getNextLine(nextLine);
		if(nextToNextLine==null) {
			return false;
		}
		return nextToNextLine.isJammed();
	}
	
	private Line getNextLine(Line line) {
		Node crossing=line.getEnd();
		Node nextNode = RouteTableService.getInstance().getNextNode(crossing, getDestinationNode());
		if(nextNode==null) {
			return null;
		}

		Line nextLine = WorkspaceManager.getInstance().getNetwork().getLine(crossing, nextNode);
		return nextLine;
		
	}

	public synchronized double getVelocity() {
		if (currentLine == null) {
			velocity = 0;
		}
		return velocity;
	}

	public synchronized void stepBreak() {
		this.throttle = Throttle.BREAK;
	}

	private void stepGas() {
		this.throttle = Throttle.ACCELERATE;
	}

	@Override
	public String toString() {
		String s1 = id.replaceAll("Pod", "P");

		return s1 + " (" + (float) distanceSinceLastNode + "/" + lastUpdatedTime + ")";
	}

	public synchronized Passenger getPassenger() {
		return passenger;
	}

	public void sendEvent(long tick, SimEvent event) {
		history.add(event);
		event.act(tick, this);
	}

	public boolean canCollide(double velocityDiff, double gap) {
		if (velocityDiff < 0) {
			return false;
		}

		double sd = getStoppingDistance(velocityDiff);
		if (gap > sd + 2) {
			return false;
		} else {
			return true;
		}
	}

	public void unloadPassenger() {
		this.passenger = null;

	}

	public void lockForMerging() {
		this.mergeLock = true;
	}

	public boolean isMergeLockOn() {
		return mergeLock;
	}

	public boolean isCrashed() {
		return isCrashed;
	}
	
	public double getMinGap() {
		return 2*velocity+getStoppingDistance()+Config.getInstance().getMinGap()+Config.getInstance().getPodLen();
	}

	

	
	

}
