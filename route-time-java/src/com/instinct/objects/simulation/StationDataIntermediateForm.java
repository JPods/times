package com.instinct.objects.simulation;

public class StationDataIntermediateForm {
private String coordinate;
	
	private String id;
	
	private String name;

	
	private int totalArrived;
	private int totalLeft;
	
	private double avgTimeSpent;
	
	public StationDataIntermediateForm(StationData stData) {
		this.id=stData.getId();
		this.name=stData.getName();
		this.coordinate=stData.getCoordinate();
		this.avgTimeSpent=stData.getStat().getAvgTimeSpent();
		this.totalArrived=stData.getStat().getTotalArrived();
		this.totalLeft=stData.getStat().getTotalLeft();
	}
	
	public StationData getStationData() {
		StationData stData=new StationData();
		stData.setCoordinate(coordinate);
		stData.setName(name);
		stData.setId(id);
		stData.getStat().setAvgTimeSpent(avgTimeSpent);
		stData.getStat().setTotalArrived(totalArrived);
		stData.getStat().setTotalLeft(totalLeft);
		return stData;
	}
}
