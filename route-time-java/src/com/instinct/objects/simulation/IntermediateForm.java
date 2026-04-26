package com.instinct.objects.simulation;

public class IntermediateForm {
	private String srcId;
	private String destinationId;
	private double avgTime;
	public IntermediateForm(String srcId, String destinationId, double avgTime) {
		super();
		this.srcId = srcId;
		this.destinationId = destinationId;
		this.avgTime = avgTime;
	}
	public String getSrcId() {
		return srcId;
	}
	public String getDestinationId() {
		return destinationId;
	}
	public double getAvgTime() {
		return avgTime;
	}
	
}