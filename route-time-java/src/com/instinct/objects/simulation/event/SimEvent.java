package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public interface SimEvent {

	public void act(long tick, Pod pod);
	
	public String getHistory();
	
	public long getTick();
}
