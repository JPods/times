package com.instinct.config;

import com.instinct.service.StaticUtil;

public class Config {

	private static Config instance=new Config();
	
	public static Config getInstance() {
		return instance;
	}
	public static void setInstance(Config instance) {
		Config.instance = instance;
	}


	
	private int minGap = 3;   // 2 meter
	 //0.6 sec
	//Network level settings
	private int podLen = 3;
	

	private int podSpace=3;
	

	private int walkingSpeedKMPH=10;
	
	private int podsPerKm=20;

	private Config() {
	}
	
	public int getPodsPerKm() {
		return podsPerKm;
	}
	
	
	public int getMinGap() {
		return minGap;
	}


	public int getPodLen() {
		return podLen;
	}
	
	public int getPodSpace() {
		return podSpace;
	}
	
	
	


	public double getWalkingDistanceInMinsInMeters(int i) {
			double t = (walkingSpeedKMPH*1000*i*60)/3600;
			return StaticUtil.round(t);
	}

	public void setMinGap(int minGap) {
		this.minGap = minGap;
	}


	public void setPodLen(int podLen) {
		this.podLen = podLen;
	}
	
	public int getWalkingSpeedKMPH() {
		return walkingSpeedKMPH;
	}
	
	

}
