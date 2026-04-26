package com.instinct.service;

import com.instinct.objects.network.Station;

public class RoundRobinHolder {

	private RoundRobin<Station> rr=null;

	private static RoundRobinHolder instance=new RoundRobinHolder();
	
	private RoundRobinHolder() {
		
	}
	
	public static RoundRobinHolder getInstance() {
		return instance;
	}
	
	public RoundRobin<Station> getScheduler() {
		return rr;
	}
	
	public void init() {
		rr=new RoundRobin<Station>(WorkspaceManager.getInstance().getNetwork().getAllStations());
	}
}
