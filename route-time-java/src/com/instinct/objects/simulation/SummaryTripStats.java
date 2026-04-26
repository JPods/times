package com.instinct.objects.simulation;


import com.instinct.objects.Passenger;
import com.instinct.service.StaticUtil;
import com.instinct.service.WorkspaceManager;


public class SummaryTripStats {
	private int passengersTraveling;
	
	private int passengersWaiting;
	
	private double totalTripTime;
	
	private double longestTripTime;
	
	private double longestWaitingTime;
	
	private double totalWaitingTime;
	
	private double slowestVelocity=Double.MAX_VALUE;
	
	private double totalVelocity;
	
	private double totalTripDistance;
	
	private int passengersCarried;
	
	private int tick=0;
	
	private long startTimeMs;
	
	private long endTimeMs;
	
	private int numberOfTripsNotEmpty;
	
	private int numberOfTripsEmpty;
	
	private long simulatedTime;
	
	private double distanceTravelledByEmptyVehicles;
	
	private double distanceTravelledByFullVehicles;

	public int getPassengersTraveling() {
		return passengersTraveling;
	}

	public int getPassengersWaiting() {
		return passengersWaiting;
	}

	public double getTotalTripTime() {
		return totalTripTime;
	}

	public double getLongestTripTime() {
		return longestTripTime;
	}


	public double getTotalWaitingTime() {
		return totalWaitingTime;
	}


	public double getTotalVelocity() {
		return totalVelocity;
	}


	public int getPassengersCarried() {
		return passengersCarried;
	}

	public int getTick() {
		return tick;
	}

	public long getStartTimeMs() {
		return startTimeMs;
	}

	public long getEndTimeMs() {
		return endTimeMs;
	}

	public int getNumberOfTripsNotEmpty() {
		return numberOfTripsNotEmpty;
	}

	public int getNumberOfTripsEmpty() {
		return numberOfTripsEmpty;
	}

	public long getSimulatedTime() {
		return simulatedTime;
	}
	
	public double getDistanceTravelledByEmptyVehicles() {
		return distanceTravelledByEmptyVehicles;
	}

	public double getDistanceTravelledByFullVehicles() {
		return distanceTravelledByFullVehicles;
	}
	


	public double getAvgTripTimeInMin() {
		int totalTrips=getTotalTrips();
		if(totalTrips==0) {
			return 0;
		}
		return StaticUtil.round(totalTripTime/(totalTrips*(WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()*60)));
	}

	public double getLongestTripTimeInMin() {
		return StaticUtil.round(longestTripTime/(WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()*60));
	}

	public double getAvgWaitingTime() {
		int totalTrips=getTotalTrips();
		if(totalTrips==0) {
			return 0;
		}		return StaticUtil.round(totalWaitingTime/totalTrips);
	}

	public double getLongestWaitingTime() {
		return StaticUtil.round(longestWaitingTime);
	}
	
	public double getLongestWaitingTimeInMin() {
		return StaticUtil.round(longestWaitingTime/(WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()*60));
	}
	public double getAvgVelocity() {
		int totalTrips=getTotalTrips();
		if(totalTrips==0) {
			return 0;
		}
		return StaticUtil.round(totalVelocity/totalTrips);
	}

	public double getAvgVelocityInKMPH() {
		double kmphVel=getAvgVelocity()*WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()*3600/1000;
		return StaticUtil.round(kmphVel);
	}

	public double getSlowestVelocityInKMPH() {
		double kmphVel=slowestVelocity*WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()*3600/1000;
		return StaticUtil.round(kmphVel);
	}

	
	public double getSlowestVelocity() {
		return StaticUtil.round(slowestVelocity);
	}

	public double getAvgTripDistance() {
		int totalTrips=getTotalTrips();
		if(totalTrips==0) {
			return 0;
		}
		return StaticUtil.round(StaticUtil.round(totalTripDistance/totalTrips));
	}

	private int getTotalTrips() {
		return numberOfTripsNotEmpty+numberOfTripsEmpty;
	}

	public double getTotalTripDistanceInKM() {
		return StaticUtil.round(totalTripDistance/1000);
	}

	public double getAvgTripDistanceInKM() {
		return StaticUtil.round(StaticUtil.round(getAvgTripDistance()/1000));
	}

	public double getTotalTripDistance() {
		return StaticUtil.round(totalTripDistance);
	}
	
	public void logPodExit(Passenger p, int tick) {
		if(p.isCalled()) {
			numberOfTripsEmpty++;
		} else {
			numberOfTripsNotEmpty++;
			passengersCarried+=1;
			passengersTraveling--;
		}
		totalTripDistance=totalTripDistance+p.getDistanceTraveled();
		totalWaitingTime=totalWaitingTime+p.getWaitingTime();
		totalTripTime=totalTripTime+p.getTravelTime();
		double speed=p.getSpeed(); 
		totalVelocity=totalVelocity+speed;
		updateExtremes(p);
	}

	public void logPassengerEntry(Passenger p) {
		if(p.isCalled()) {
			return;
		}
		passengersWaiting++;
	}

	public void logPassengerStartMoving(Passenger passenger) {
		if(passenger.isCalled()) {
			return;
		}
		passengersWaiting--;
		passengersTraveling++;
	}
	
	
	private void updateExtremes(Passenger p) {
		if(p.getFullTripTime()>longestTripTime) {
			longestTripTime=p.getFullTripTime();
		}
		
		if(p.getWaitingTime()>longestWaitingTime) {
			longestWaitingTime=p.getWaitingTime();
		}
		
		if(slowestVelocity>p.getSpeed()) {
			slowestVelocity=p.getSpeed();
		}
	}
}
