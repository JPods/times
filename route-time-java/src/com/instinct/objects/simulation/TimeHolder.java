package com.instinct.objects.simulation;

public class TimeHolder {

	private double totalTime=0;
	
	private int count=0;
	
	private double avgTime;
	
	public TimeHolder(double avgTime) {
		this.avgTime=avgTime;
	}
	
	public TimeHolder() {
	}

	public void addTime(double time) {
		this.totalTime=totalTime+time;
		count=count+1;
		avgTime=totalTime/count;
	}
	
	public double getAvgTime() {
		return avgTime;
	}
}
