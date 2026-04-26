package com.instinct.objects.simulation.event;

import com.instinct.objects.pod.Pod;

public class PodFollowingEvent implements SimEvent {

	private StringBuilder sb = new StringBuilder();

	private long tick;

	@Override
	public long getTick() {
		return tick;
	}

	@Override
	public void act(long tick, Pod pod) {

		this.tick = tick;
		sb.append(", Line:"+pod.getCurrentLine().getId());

		Pod podAhead = pod.getCurrentLine().getPodQueue().getPodAhead(pod);
		if (podAhead == null) {
			sb.append("just crossed line");
			pod.stepBreak(); // pod just crossed line, don't take chance, step
								// break
			return;
		}
		double gap = podAhead.getDistanceSinceLastNode() - pod.getDistanceSinceLastNode();
		sb.append(", gap:" + gap + ", velocity:" + pod.getVelocity());
		double minGapRequired=pod.getMinGap();
		sb.append(", Min Required Gap:"+minGapRequired);
		if (gap >minGapRequired) {
			sb.append(", gap is good");
			pod.stepGasIfSpeedIsLow();
		} else {
			sb.append(", stepping break");
			pod.stepBreak();
		}

		sb.append(", Last Node:" + pod.getCurrentLine().getStart());
		sb.append(", Next Node:" + pod.getCurrentLine().getEnd());
		sb.append(", Distance since last Node:" + pod.getDistanceSinceLastNode());
		sb.append(", Distance from next Node:" + (pod.getCurrentLine().getLength() - pod.getDistanceSinceLastNode()));
		sb.append(", Pod Ahead:" + podAhead.getId());
	}

	@Override
	public String getHistory() {
		return this.getClass().getSimpleName() + sb.toString();
	}
}
