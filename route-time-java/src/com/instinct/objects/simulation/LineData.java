package com.instinct.objects.simulation;

import java.io.Serializable;

import com.instinct.objects.network.Line;

public class LineData implements Serializable {
	private String start;
	private String end;
	private String lineId;
	private PodQueueStat stat=new PodQueueStat();

	public void setData(Line line) {
		this.start = "Lat:" + line.getStart().getLat() + ", Lon:" + line.getStart().getLon();
		this.end = "Lat:" + line.getEnd().getLat() + ", Lon:" + line.getEnd().getLon();
		stat.setData(line.getPodQueue());
		this.lineId=line.getId();
	}

	public PodQueueStat getStat() {
		return stat;
	}

	public String getStart() {
		return start;
	}

	public String getEnd() {
		return end;
	}
	
	public String getLineId() {
		return lineId;
	}

	public void setStart(String start) {
		this.start = start;
	}

	public void setEnd(String end) {
		this.end = end;
	}

	public void setLineId(String lineId) {
		this.lineId = lineId;
	}

	public void setStat(PodQueueStat stat) {
		this.stat = stat;
	}

}
