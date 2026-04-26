package com.instinct.objects.simulation.event;

import com.instinct.config.Config;
import com.instinct.objects.Passenger;
import com.instinct.objects.network.Station;
import com.instinct.objects.pod.Pod;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.WorkspaceManager;

public class ParkedPodAheadEvent implements SimEvent {

	private StringBuilder sb = new StringBuilder();

	private long tick;

	@Override
	public long getTick() {
		return tick;
	}

	@Override
	public void act(long tick, Pod pod) {
		this.tick = tick;

		if (ifWithinBayArea(pod)) {
			sb.append(",within pod area");
			if (tooCloseToPodAhead(pod)) {
				sb.append(", too close to Pod ahead");
				if (pod.getVelocity() > 0.0) {
					pod.stepBreak();
				} else {
					pod.sendEvent(tick, new PodParkingEvent());
				}
			} else {
				sb.append(", move if possible");
				pod.sendEvent(tick, new PodFollowingEvent());
			}
		} else if (pod.getVelocity() == 0.0 && waitingForEmptySlotWithNoPassengerAtStation(pod)) {
			sb.append(", evicting pod");
			evictPod(pod);
		} else {
			sb.append(", move if possible outside parking");
			pod.sendEvent(tick, new LeadPodEvent());
		}
	}

	private void evictPod(Pod pod) {
		int time = GlobalTimeKeeper.getInstance().getTime();
		Station st = (Station) pod.getCurrentLine().getEnd();
		Passenger p = new Passenger(st, pod.getPassenger().getStart(), time, false, true);
		WorkspaceManager.getInstance().getWorkingSim().getSummary().logPassengerEntry(p);
		st.addPassenger(p);
		st.putPassengersToPods(time);
	}

	private boolean waitingForEmptySlotWithNoPassengerAtStation(Pod pod) {
		Pod podAhead = pod.getCurrentLine().getPodQueue().getPodAhead(pod);
		double gap = podAhead.getDistanceSinceLastNode() - pod.getDistanceSinceLastNode();
		if (gap < 2) {
			Station st = (Station) pod.getCurrentLine().getEnd();
			return st.getPassengerQueue().size() == 0;
		}
		return false;
	}

	
	private boolean tooCloseToPodAhead(Pod pod) {
		Pod podAhead = pod.getCurrentLine().getPodQueue().getPodAhead(pod);
		double gap = podAhead.getDistanceSinceLastNode() - pod.getDistanceSinceLastNode();
		return gap < pod.getMinGap();
	}

	private boolean ifWithinBayArea(Pod pod) {
		return getBayLength(pod) > (pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode());
	}

	private double getBayLength(Pod pod) {
		Station st = (Station) pod.getCurrentLine().getEnd();
		double bayLength = st.getPodQueue().getCapacity() * Config.getInstance().getPodSpace();
		return bayLength;
	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName() + sb.toString();
	}
}
