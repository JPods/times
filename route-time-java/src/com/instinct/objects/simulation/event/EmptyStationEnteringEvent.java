package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class EmptyStationEnteringEvent implements SimEvent {

	private long tick;
	
	@Override
	public long getTick() {
		return tick;
	}
	
	@Override
	public void act(long tick, Pod pod) {
		this.tick=tick;
		double gap = pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode();
		if (gap < pod.getMinGap()+4) {
			pod.sendEvent(tick, new PodParkingEvent());
		} else {
			if(gap<pod.getMinGap()) {
				pod.stepBreak();
			}  else  {
				pod.stepGasIfSpeedIsLow();
			}
		}		
	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName();
	}

	

}
