package com.instinct.objects.simulation;

import java.io.Serializable;

import com.instinct.objects.network.PodQueue;

public class PodQueueStat implements Serializable {

	private int totalArrived;
	private int totalLeft;
	
	private double avgTimeSpent;
	private PodQueue pq;
	
	
	public void setData(PodQueue pq) {
		this.pq=pq;
		load();
	}

	public void load() {
		if(pq==null) {
			return;
		}
		this.totalArrived=pq.getTotalPodsEntered();
		this.totalLeft=pq.getTotalPodsExited();
		this.avgTimeSpent=pq.getAvgTimeSpend();
	}

	public int getTotalArrived() {
		return totalArrived;
	}

	public int getTotalLeft() {
		return totalLeft;
	}

	public double getAvgTimeSpent() {
		return avgTimeSpent;
	}

	public void setTotalArrived(int totalArrived) {
		this.totalArrived = totalArrived;
	}

	public void setTotalLeft(int totalLeft) {
		this.totalLeft = totalLeft;
	}

	public void setAvgTimeSpent(double avgTimeSpent) {
		this.avgTimeSpent = avgTimeSpent;
	}
	
	
}
