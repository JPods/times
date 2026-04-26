package com.instinct.config;

import java.awt.Color;
import java.util.HashMap;
import java.util.Map;

import com.instinct.service.WorkspaceManager;

public enum TimeColor {


	GREEN(0,5,102,255,0), GREEN_YELLOW(5,10,191,255,0), YELLOW(10,15,255,255,49), YELLOW_ORANGE(15,20,255,219,88), ORANGE_BROWN(20,25,255,179,71),ORANGE_RED(25,30,255,90,54), RED(30,1000,255,28,0);
	
	private double min, max;
	private int R,G,B;
	private Color c;
	private static Map<Integer, Color> metalicColors=new HashMap<Integer, Color>();
	
	static {
		metalicColors.put(5, Color.green);
		metalicColors.put(10, Color.blue);
		metalicColors.put(20, Color.yellow);
		metalicColors.put(30, Color.red);
		
	}
	
	private TimeColor(int min, int max, int r, int g, int b) {
		this.min=min;
		this.max=max;
		this.R=r;
		this.G=g;
		this.B=b;
		c=new Color(R,G,B);
		
	}
	
	private boolean within(int time) {
		return time>=min && time<=max;
	}
	
	public static TimeColor getColorByMinute(int timeInMinute) {
		for(TimeColor tc:TimeColor.values()) {
			if(tc.within(timeInMinute)) {
				return tc;
			}
		}
		return RED;
	}
	public static TimeColor getColor(int time) {
		int timeInMinute=(time/WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec())/60;
		return getColorByMinute(timeInMinute);

	}
	
	public Color getColor() {
		return c;
	}
	
	public static Color getMetalicColorByMinute(int timeInMin) {
		return metalicColors.get(timeInMin);
	}

}
