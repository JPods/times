package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class MergeAheadEvent implements SimEvent {

	private StringBuilder sb = new StringBuilder();

	private long tick;

	@Override
	public long getTick() {
		return tick;
	}

	@Override
	public void act(long tick, Pod pod) {
		this.tick = tick;
		double gap = pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode();
		Pod mergingPod = pod.getConvergingPod();
		
		if (pod.isMergeLockOn()) {
			sb.append(", Merge Lock On, delegating to LeadPodEvent");
			pod.sendEvent(tick, new LeadPodEvent());
			return;
		}

		if (mergingPod != null && mergingPod.isMergeLockOn()) {
			moveIfSpace(pod);
			return;
		}

		if (gap > 30) {
			sb.append(", Far from Merging, delegating to LeadPodEvent");
			pod.sendEvent(tick, new LeadPodEvent());
			return;
		}
		tryToGetLock(pod, mergingPod);
	}

	private void tryToGetLock(Pod pod, Pod mergingPod) {
		if (mergingPod != null && mergingPod.getCurrentLine().isPartOfTrafficCircle()) {
			mergingPod.lockForMerging();
			moveIfSpace(pod);
		} else if (pod.getCurrentLine().isPartOfTrafficCircle()) {
			pod.lockForMerging();
			sb.append(", locking and delegating to LeadPodEvent, on traffic circle line");
			pod.sendEvent(tick, new LeadPodEvent());
		} else if (onSmallLine(pod)) {
			pod.lockForMerging();
			sb.append(", locking and delegating to LeadPodEvent, on small line");
			pod.sendEvent(tick, new LeadPodEvent());
		} else if (isConvergingPodBehind(pod)) {
			pod.lockForMerging();
			sb.append(", locking and delegating to LeadPodEvent");
			pod.sendEvent(tick, new LeadPodEvent());
		} else if (isDeadLock(pod)) {
			sb.append(", locking for resolving deadlock and delegating to LeadPodEvent");
			pod.lockForMerging();
			pod.sendEvent(tick, new LeadPodEvent());
		} else {
			// sb.append(" Head Clearance:" + gap + ", velocity:" +
			// pod.getVelocity());
			moveIfSpace(pod);
			sb.append(", Line:" + pod.getCurrentLine().getId());
			sb.append(", Last Node:" + pod.getCurrentLine().getStart());
			sb.append(", Next Node:" + pod.getCurrentLine().getEnd());
			sb.append(", Distance since last Node:" + pod.getDistanceSinceLastNode());
			sb.append(", Distance from next Node:" + (pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode()));
		}
	}

	private void moveIfSpace(Pod pod) {
		double gap=pod.getCurrentLine().getLength()-pod.getDistanceSinceLastNode();
		if(gap<pod.getMinGap()) {
			sb.append(", stepping Break");
			pod.stepBreak();
		}  else  {
			sb.append(", stepping Gas");
			pod.stepGasIfSpeedIsLow();
		}
	}

	private boolean onSmallLine(Pod pod) {
		return pod.getCurrentLine().getLength() < 50;
	}

	private boolean isDeadLock(Pod pod) {
		Pod mergingPod = pod.getConvergingPod();
		if (mergingPod == null) {
			return false;
		}
		if (mergingPod.getVelocity() == pod.getVelocity() && pod.getVelocity() == 0.0) {
			return true;
		}
		return false;
	}

	private boolean isConvergingPodBehind(Pod pod) {
		Pod mergingPod = pod.getConvergingPod();
		if (mergingPod == null) {
			return true;
		}
		double gap = pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode();
		double mergingPodGap = mergingPod.getCurrentLine().getLength() - mergingPod.getDistanceSinceLastNode();
		double d = mergingPodGap - gap;
		return d > 10;
	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName() + sb.toString();
	}
}
