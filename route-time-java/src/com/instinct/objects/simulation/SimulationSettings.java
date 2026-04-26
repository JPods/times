package com.instinct.objects.simulation;

import java.io.Serializable;


public class SimulationSettings implements Serializable {

	private double acc = 0;

	private double accInG = 1;

	private double decc = 0;

	private double deccInG = 1;
	private double maxVelocityInTU = 6;

	private int maxVelocityInKMPH = 60;

	private int disembarkingTimeInSec = 20;

	private int embarkingTimeInSec = 20;

	private int ticketingTimeInSec = 30;

	private int stationEntryTimeInSec = 40;

	private int stationExitTimeInSec = 40;

	private int slowMotion = 0;

	private int timeResolutionPerSec = 9;
	private int podsPerStation = 4;
	
	private int graceDistance=0;
	
	
	private String jpodBarColor="#4CAF50", carBarColor="#F44336", busBarColor="#FF9800", trainBarColor="#2196F3";
	

	public String getJpodBarColor() {
		return jpodBarColor;
	}



	public void setJpodBarColor(String jpodBarColor) {
		this.jpodBarColor = jpodBarColor;
	}



	public String getCarBarColor() {
		return carBarColor;
	}



	public void setCarBarColor(String carBarColor) {
		this.carBarColor = carBarColor;
	}



	public String getBusBarColor() {
		return busBarColor;
	}



	public void setBusBarColor(String busBarColor) {
		this.busBarColor = busBarColor;
	}



	public String getTrainBarColor() {
		return trainBarColor;
	}



	public void setTrainBarColor(String trainBarColor) {
		this.trainBarColor = trainBarColor;
	}



	public SimulationSettings() {
		setAccInG(1.0);
		setDeccInG(1.0);
	}

	
	
	public int getPodsPerStation() {
		return podsPerStation;
	}



	public void setPodsPerStation(int podsPerStation) {
		this.podsPerStation = podsPerStation;
	}



	public double getAccInTU() {
		return accInG * 9.8 / (timeResolutionPerSec*timeResolutionPerSec);

	}

	public int getDisembarkingTimeInSec() {
		return disembarkingTimeInSec;
	}

	public void setDisembarkingTimeInSec(int disembarkingTimeInSec) {
		this.disembarkingTimeInSec = disembarkingTimeInSec;
	}

	public int getEmbarkingTimeInSec() {
		return embarkingTimeInSec;
	}

	public void setEmbarkingTimeInSec(int embarkingTimeInSec) {
		this.embarkingTimeInSec = embarkingTimeInSec;
	}

	public int getTicketingTimeInSec() {
		return ticketingTimeInSec;
	}

	public void setTicketingTimeInSec(int ticketingTimeInSec) {
		this.ticketingTimeInSec = ticketingTimeInSec;
	}

	public int getStationEntryTimeInSec() {
		return stationEntryTimeInSec;
	}

	public void setStationEntryTimeInSec(int stationEntryTimeInSec) {
		this.stationEntryTimeInSec = stationEntryTimeInSec;
	}

	public int getStationExitTimeInSec() {
		return stationExitTimeInSec;
	}

	public void setStationExitTimeInSec(int stationExitTimeInSec) {
		this.stationExitTimeInSec = stationExitTimeInSec;
	}

	public double getAccInG() {
		return accInG;
	}

	public double getDeccInTU() {
		return deccInG * 9.8 / (timeResolutionPerSec*timeResolutionPerSec);
	}

	public double getDeccInG() {
		return deccInG;
	}

	public double getMaxVelocityInTU() {
		double mPerSec = maxVelocityInKMPH * 1000 / 3600;
		return mPerSec / timeResolutionPerSec;
	}

	public int getMaxVelocityInKMPH() {
		return maxVelocityInKMPH;
	}

	public int getSlowMotion() {
		return slowMotion;
	}

	
	public int getTimeResolutionPerSec() {
		return timeResolutionPerSec;
	}

	public void setAccInG(double accInG) {
		this.accInG = accInG;
		this.acc = convert(accInG);
	}

	private double convert(double a) {
		return a * 9.8 / timeResolutionPerSec;
	}

	public void setDeccInG(double deccInG) {
		this.deccInG = deccInG;

	}


	public void setMaxVelocityInKMPH(int velocityKmph) {
		this.maxVelocityInKMPH = velocityKmph;
		double mPerSec = velocityKmph * 1000 / 3600;
		this.maxVelocityInTU = mPerSec / timeResolutionPerSec;
	}

	public void setSlowMotion(int slowMotion) {
		this.slowMotion = slowMotion;
	}

	public void setTimeResolutionPerSec(int timeResolutionPerSec) {
		this.timeResolutionPerSec = timeResolutionPerSec;
	}

	public double getMaxStoppingDistance() {
		return maxVelocityInTU * maxVelocityInTU / (2 * decc);
	}

	public int getGraceDistance() {
		return graceDistance;
	}

	public void setGraceDistance(int graceDistance) {
		this.graceDistance=graceDistance;
	}
	

}
