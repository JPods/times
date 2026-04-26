package com.instinct.objects;

import java.io.Serializable;
import java.util.concurrent.atomic.AtomicInteger;

import com.instinct.objects.network.Station;
import com.instinct.objects.simulation.SimulationSettings;
import com.instinct.service.WorkspaceManager;

public class Passenger implements Serializable {

	private Station start, end;
	private int journeyStartTime;
	private int movementStartTime;
	private int journeyEndTime;
	private double distanceTraveled;
	private String id="PS"+idGen.getAndIncrement();
	private static AtomicInteger idGen=new AtomicInteger(0);		
	private boolean isEvicted=false;
	private boolean isCalled=false;
	
	public Passenger(Station start, Station end, int time) {
		this(start,end,time,false,false);
	}

	public Passenger(Station start, Station end, int time, boolean isCalled, boolean isEvicted) {
		if(start==null || end==null) {
			System.err.println("Empty entry/exit");
			System.exit(9);
		}
		this.start=start;
		this.end=end;
		this.journeyStartTime=time;
		this.isEvicted=isEvicted;
		this.isCalled=isCalled;
	}

	public void addDistanceTraveled(double distance) {
		distanceTraveled=distanceTraveled+distance;
	}

	
	public boolean isCalled() {
		return isCalled;
	}

	public boolean isEvicted() {
		return isEvicted;
	}
	
	public boolean isDummy() {
		return isEvicted==false && isCalled==false;
	}
	
	public void setMovementStartTime(int movementStartTime) {
		this.movementStartTime = movementStartTime;
	}

	public int getJourneyEndTime() {
		return journeyEndTime;
	}

	public void setJourneyEndTime(int journeyEndTime) {
		this.journeyEndTime = journeyEndTime;
	}

	public int getJourneyStartTime() {
		return journeyStartTime;
	}

	public int getFullTripTime() {
		SimulationSettings cfg=WorkspaceManager.getInstance().getWorkingSim().getSettings();
		int t=cfg.getStationEntryTimeInSec()+cfg.getTicketingTimeInSec()+cfg.getEmbarkingTimeInSec()+cfg.getDisembarkingTimeInSec()+cfg.getStationExitTimeInSec();
		int t1=t*cfg.getTimeResolutionPerSec();
		int t2=t1+getWaitingTime()+getTravelTime();
		return t2;
	}
	
	public int getTravelTime() {
		return journeyEndTime-movementStartTime;
	}
	
	public Station getStart() {
		return start;
	}

	public Station getEnd() {
		return end;
	}
	
	public int getWaitingTime() {
		return movementStartTime-journeyStartTime;
	}



	@Override
	public String toString() {
		return "Host [journeyStartTime=" + journeyStartTime + ", movementStartTime=" + movementStartTime + ", journeyEndTime=" + journeyEndTime
				+ ", distanceTraveled=" + distanceTraveled + ", id=" + id + "]";
	}


	public String getId() {
		return id;
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
		Passenger other = (Passenger) obj;
		if (id == null) {
			if (other.id != null)
				return false;
		} else if (!id.equals(other.id))
			return false;
		return true;
	}

	
	public int getMovementStartTime() {
		return movementStartTime;
	}
	
	public double getDistanceTraveled() {
		return distanceTraveled;
	}

	public double getSpeed() {
		return distanceTraveled/getTravelTime();
	}
	
}
