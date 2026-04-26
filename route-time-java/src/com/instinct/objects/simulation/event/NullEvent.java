package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class NullEvent implements SimEvent {

	private long tick;
	
	@Override
	public long getTick() {
		return tick;
	}
	
	@Override
	public void act(long tick, Pod pod) {

	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName();
	}
}
