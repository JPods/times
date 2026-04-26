package com.instinct.objects.simulation.event;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.pod.Pod;

public class LeadPodEvent implements SimEvent {

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
		sb.append(" Destination:"+pod.getPassenger().getEnd().getId());
		sb.append(", Head Clearance:"+gap+", velocity:"+pod.getVelocity());
		sb.append(", Line:"+pod.getCurrentLine().getId());
		sb.append(", Min Gap:"+pod.getMinGap());

		if(gap<pod.getMinGap()) {
			sb.append(", stepping Break");
			pod.stepBreak();
		}  else  {
			sb.append(", stepping Gas");
			pod.stepGasIfSpeedIsLow();
		}
		sb.append(", Last Node:"+pod.getCurrentLine().getStart());
		sb.append(", Next Node:"+pod.getCurrentLine().getEnd());
		sb.append(", Distance since last Node:"+pod.getDistanceSinceLastNode());
		sb.append(", Distance from next Node:"+(pod.getCurrentLine().getLength()-pod.getDistanceSinceLastNode()));
			
	}



	private double getHeadClearance(Pod pod) {
		double thisLineGap=pod.getCurrentLine().getLength()-pod.getDistanceSinceLastNode();
		Line nextLine=pod.getNextLine();
		if(nextLine==null) {
			return thisLineGap;
		}
		
		if(nextLine.getEnd() instanceof Station) {
			if(nextLine.getPodQueue().size()>3) {
				return thisLineGap;
			}
		}
		sb.append(", Next Line:"+nextLine.getId());
		double nextLineClearance=nextLine.computeLineGap();
		double lineGap=thisLineGap+nextLineClearance;
		if(nextLine.getPodQueue().size()==0 && nextLine.getLength()<10) {
			Node n=nextLine.getEnd();
			if(n instanceof Switch) {
				Switch sw=(Switch)n;
				if(sw.getExitCount()==2) {
					double min=Math.min(sw.getExit1().computeLineGap(), sw.getExit2().computeLineGap());
					return lineGap+min;
				} else if(sw.getEntryCount()==2) {
					Line otherLine=sw.getOtherEntry(nextLine);
					double otherGap=otherLine.getHeadGap();
					if(otherGap>20) {
						return lineGap+sw.getExit().computeLineGap();
					}
				} else if(sw.getEntryCount()==1 && sw.getExitCount()==1){
					return lineGap+sw.getExit().computeLineGap();
				}
			}
		} 
		return lineGap;
	}
	
	

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName()+sb.toString();
	}
}
