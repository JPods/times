package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class TickEvent implements SimEvent {

	private Pod pod = null;
	private long tick;

	@Override
	public long getTick() {
		return tick;
	}

	@Override
	public void act(long tick, Pod pod) {
		this.tick = tick;

		this.pod = pod;
		if (isFirstPod(pod)) {
			if (pod.isParked()) {
				pod.sendEvent(tick, new NullEvent());
			} else if (pod.getCurrentLine().isConverging()) {
				pod.sendEvent(tick, new MergeAheadEvent());
			} else if (pod.isOnLastLine()) {
				pod.sendEvent(tick, new StationEnteringEvent());
			} else if (isPodLeavingStation(pod)) {
				pod.sendEvent(tick, new StationLeavingEvent());
			} else {
				pod.sendEvent(tick, new LeadPodEvent());
			}
		} else {
			if (pod.isParked()) {
				pod.sendEvent(tick, new NullEvent());
			} else if (pod.isOnLastLine()) {
				pod.sendEvent(tick, new StationEnteringEvent());
			} else {
				pod.sendEvent(tick, new PodFollowingEvent());
			}
		}

	}

	private boolean isFirstPod(Pod pod) {
		return pod.getCurrentLine().getPodQueue().getPodAhead(pod) == null;
	}

	private boolean isPodLeavingStation(Pod pod) {
		if (pod.getPassenger().getStart().equals(pod.getCurrentLine().getEnd())) {
			return true;
		}
		return false;
	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName();
	}
}
