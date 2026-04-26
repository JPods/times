package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class StationEnteringEvent implements SimEvent {

	private StringBuilder sb = new StringBuilder();

	private long tick;

	@Override
	public long getTick() {
		return tick;
	}

	@Override
	public void act(long tick, Pod pod) {
		this.tick = tick;
		sb.append(", Line:" + pod.getCurrentLine().getId());
		if (pod.getCurrentLine().getPodQueue().getPodAhead(pod)!=null) {
			pod.sendEvent(tick, new PodFollowingEvent());
		} else {
			pod.sendEvent(tick, new EmptyStationEnteringEvent());
		}
	}


	@Override
	public String getHistory() {
		return this.getClass().getSimpleName() + sb.toString();
	}
}
