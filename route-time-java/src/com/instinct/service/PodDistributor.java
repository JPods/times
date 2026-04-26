package com.instinct.service;

import java.util.List;

import com.instinct.objects.Passenger;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Station;

public class PodDistributor {

	private static PodDistributor instance = new PodDistributor();

	public static PodDistributor getInstance() {
		return instance;
	}

	private PodDistributor() {

	}

	public void adjust(int time) {
		adjustForWaitingPassengerToEmbark(time);
	}

	private void adjustForWaitingPassengerToEmbark(int time) {
		for (Station s : WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			if (s.getPodQueue().size() == 0 && s.getPassengerQueue().size() > 0 && s.getEntry().getPodQueue().size() == 0) {
				Passenger p = s.getPassengerQueue().peek();
				int waitingTime = time - p.getJourneyStartTime();
				if (waitingTime > WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec() * 300) {
					callPod(s, time);
				}
			}
		}
	}



	private void callPod(Station s, int time) {
		Station st = getClosestNeighbourWithFreePod(s);
		if (st == null) {
			return;
		}
		
		st.addPassenger(new Passenger(st, s, time, true,false));

	}

	

	private Station getClosestNeighbourWithFreePod(Station st) {
		Station closestSt = null;
		double closestDistance = Double.MAX_VALUE;
		for (Station s : WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			if (st.equals(s) || s.getPodQueue().size() == 0 || s.getPassengerQueue().size() != 0) {
				continue;
			}
			List<Line> path = RouteTableService.getInstance().getPath(s, st);
			if (path == null) {
				continue;
			}
			double d = calculateDistance(path);
			if (closestDistance > d) {
				closestDistance = d;
				closestSt = s;
			}
		}
		return closestSt;
	}

	private double calculateDistance(List<Line> path) {
		double d = 0;
		for (Line l : path) {
			d = d + l.getLength();
		}
		return d;
	}

}
