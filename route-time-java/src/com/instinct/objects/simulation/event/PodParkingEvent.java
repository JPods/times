package com.instinct.objects.simulation.event;

import com.instinct.objects.Passenger;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Station;
import com.instinct.objects.pod.Pod;
import com.instinct.objects.pod.Throttle;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.WorkspaceManager;

public class PodParkingEvent implements SimEvent {

	private long tick;
	
	@Override
	public long getTick() {
		return tick;
	}
	
	@Override
	public void act(long tick, Pod pod) {
		this.tick=tick;

		park(pod);
	}

	private void park(Pod pod) {
		int time = GlobalTimeKeeper.getInstance().getTime();
		Passenger passenger = pod.getPassenger();
		Line currentLine = pod.getCurrentLine();
		if (pod.getDistanceSinceLastNode() > currentLine.getLength()) {
			pod.setDistanceSinceLastNode(currentLine.getLength());
		}
		if(passenger==null) {
			System.out.println(" Null Passenger");
		} else {
			passenger.addDistanceTraveled(currentLine.getLength() - pod.getDistanceSinceLastNode());
			passenger.setJourneyEndTime(time);
			WorkspaceManager.getInstance().getWorkingSim().logPassengerExit(passenger, time);
			pod.setStartTime(0);
			pod.setThrottle(Throttle.BREAK);
			pod.setVelocity(0);
			pod.unloadPassenger();
			Station st=passenger.getEnd();
			st.getPodQueue().addPod(pod);
		}
		
		
	}
	
	@Override
	public String getHistory() {
		return this.getClass().getSimpleName();
	}
}
