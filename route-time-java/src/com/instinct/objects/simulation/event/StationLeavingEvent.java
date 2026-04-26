package com.instinct.objects.simulation.event;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Station;
import com.instinct.objects.pod.Pod;

public class StationLeavingEvent implements SimEvent {

	private StringBuilder sb=new StringBuilder();

	private long tick;
	
	@Override
	public long getTick() {
		return tick;
	}
	
	@Override
	public void act(long tick, Pod pod) {
		this.tick=tick;
		double gap=getHeadClearance(pod);
		sb.append(",gap:"+gap+", velocity:"+pod.getVelocity());
		if(gap<pod.getMinGap()) {
			sb.append(", stepping Break");
			pod.stepBreak();
		} else {
			sb.append(", stepping Gas");
			pod.stepGasIfSpeedIsLow();
		}
		
	}

	private double getHeadClearance(Pod pod) {
		
		Pod podAhead=pod.getCurrentLine().getPodQueue().getPodAhead(pod);
		if(podAhead!=null) {
			return 0;
		} 		
		
		double thisLineGap=0;
		Station st=(Station) pod.getCurrentLine().getEnd();
		Line nextLine=st.getExit();
		double totalGap=thisLineGap;
		double nextLineGap=nextLine.getPodQueue().size()==0?nextLine.getLength():nextLine.getPodQueue().getTailPod().getDistanceSinceLastNode();
		totalGap=totalGap+nextLineGap;
		return totalGap;
	}
	
	@Override
	public String getHistory() {
		return this.getClass().getSimpleName()+sb.toString();
	}
}

