package com.instinct.objects.simulation;

import java.io.Serializable;

import com.instinct.objects.network.Station;

public class StationData implements Serializable {

	private String coordinate;
	
	private String id;
	
	private String name;

	private PodQueueStat stat=new PodQueueStat();
	
	public void setData(Station st) {
		this.coordinate = "Lat:"+st.getLat()+", Lon:"+st.getLon();
		stat.setData(st.getPodQueue());
		id=st.getId();
		name=st.toString();
	}
	
	public String getId() {
		return id;
	}
	
	public PodQueueStat getStat() {
		return stat;
	}
	
	public String getCoordinate() {
		return coordinate;
	}
	
	public String getName() {
		return name;
	}

	public void setCoordinate(String coordinate) {
		this.coordinate = coordinate;
	}

	public void setId(String id) {
		this.id = id;
	}

	public void setName(String name) {
		this.name = name;
	}
	
}
