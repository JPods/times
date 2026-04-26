package com.instinct.objects.simulation;

public class LineDataIntermediateForm {
	private String start;
	private String end;
	private String lineId;
	private int totalArrived;
	private int totalLeft;
	private double avgTimeSpent;
	
	public LineDataIntermediateForm(LineData lineData) {
		this.lineId=lineData.getLineId();
		this.start=lineData.getStart();
		this.end=lineData.getEnd();
		this.avgTimeSpent=lineData.getStat().getAvgTimeSpent();
		this.totalArrived=lineData.getStat().getTotalArrived();
		this.totalLeft=lineData.getStat().getTotalLeft();
		
	}
	
	public LineData getLineData() {
		LineData lineData=new LineData();
		lineData.setEnd(end);
		lineData.setStart(start);
		lineData.setLineId(lineId);
		lineData.getStat().setAvgTimeSpent(avgTimeSpent);
		lineData.getStat().setTotalArrived(totalArrived);
		lineData.getStat().setTotalLeft(totalLeft);
		return lineData;
	}
}
