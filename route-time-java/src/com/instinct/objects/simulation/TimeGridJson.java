package com.instinct.objects.simulation;

import com.google.gson.Gson;

public class TimeGridJson {
	
	private IntermediateForm []times;
	private SummaryTripStats summary;
	private LineDataIntermediateForm[] lineData;
	private StationDataIntermediateForm[] stationData;
	private SimulationSettings settings;
	private LoadArray loadArray;
	private String networkVersion;
	
	
	public TimeGridJson(SimDataHolder simData, String networkVersion) {
		super();
		TimeGridData grid = simData.getTimes();
		this.times = grid.getIntermediateForm().toArray(new IntermediateForm[grid.getIntermediateForm().size()]);
		this.summary=simData.getSummary();
		this.lineData=simData.buildLineDataIntermediateForm();
		this.stationData=simData.buildStationDataIntermediateForm();
		this.settings=simData.getSettings();
		this.loadArray=simData.getLoad();
		this.networkVersion=networkVersion;
		
	}
	
	public LoadArray getLoadArray() {
		return loadArray;
	}

	public String getNetworkVersion() {
		return networkVersion;
	}

	
	
	public static TimeGridJson fromJson(String json) {
		Gson gson = new Gson();
		return (TimeGridJson)gson.fromJson(json, TimeGridJson.class);
	}


	public IntermediateForm[] getTimes() {
		return times;
	}
	
	public SummaryTripStats getSummary() {
		return summary;
	}

	public LineDataIntermediateForm[] getLineData() {
		return lineData;
	}

	public StationDataIntermediateForm[] getStationData() {
		return stationData;
	}

	public SimulationSettings getSettings() {
		return settings;
	}

	
}