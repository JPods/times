package com.instinct.gui;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import javax.swing.JOptionPane;

import com.instinct.gui.pad.Pad;
import com.instinct.objects.Passenger;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;
import com.instinct.objects.pod.Pod;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.RouteTableService;
import com.instinct.service.WorkspaceManager;

public class Simulator extends Thread {
	private List<Station> sts = new ArrayList<Station>(WorkspaceManager.getInstance().getNetwork().getAllStations());
	private ExecutorService executor = Executors.newFixedThreadPool(15);
	private boolean forceStop=false;
	private boolean isRunning=false;

	public Simulator() {
	}

	public boolean isRunning() {
		return isRunning;
	}

	public void run() {
		isRunning=true;
		GlobalTimeKeeper timeKeeper = GlobalTimeKeeper.getInstance();
		int time = 0;
		
		
		while (WorkspaceManager.getInstance().checkTime(time)) {
			if (forceStop == true) {
				executor.shutdown();
				break;
			}
			
			time = timeKeeper.tick();
			//recomputeRoutes(time);
			processTick(time);
			sleepIfSlowMotionEnabled();
			adjustPodsAtStations();
		
		}
		
		try {
			executor.awaitTermination(2, TimeUnit.SECONDS);
		} catch (InterruptedException e) {
			e.printStackTrace();
		}
		Pad.getInstance().showAlert("Simulation Finished");

		WorkspaceManager.getInstance().getNetwork().safeKeeping();
		Toolbar.getInstance().showSimulatorRun();
		WorkspaceManager.getInstance().getWorkingSim().setCompleted(true);
		isRunning=false;
		Pad.getInstance().notifyComponents();
	}

	private void recomputeRoutes(int time) {
		if(time%(9*180)==0) {	
			Pad.getInstance().showAlert("Recomputing Routes");
			RouteTableService.getInstance().recompute();
		}
	}

	private void adjustPodsAtStations() {
		for (Station st : WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			adjustStationPod(st);
		}

	}

	private void adjustStationPod(Station st) {
		if (isInLineClear(st) && st.getPodQueue().size() == 0 && st.getEntry().getPodQueue().size() == 0 && st.getExit().getPodQueue().size() == 0) {
			st.callPodFromDepot();
		} else if (st.getEntry().getPodQueue().size() == 0 && st.getPassengerQueue().size() == 0 && st.getPodQueue().size() == 4) {
			st.returnPodToDepot();
		}
	}
	
	private boolean isInLineClear(Station st) {
		Switch sw=(Switch) st.getEntry().getStart();
		Line inLine=sw.getEntry();
		Pod pod=inLine.getPodQueue().getHeadPod();
		if(pod==null) {
			return true;
		}
		return inLine.getLength()-pod.getDistanceSinceLastNode()>25;
	}
	

	private void sleepIfSlowMotionEnabled() {
		if (WorkspaceManager.getInstance().getWorkingSim().getSettings().getSlowMotion() > 0) {
			int timeMs = WorkspaceManager.getInstance().getWorkingSim().getSettings().getSlowMotion();
			try {
				Thread.sleep(timeMs);
			} catch (InterruptedException e) {
				e.printStackTrace();
			}
		}
	}

	private void processTick(int time) {
		generatePassengers(time);
		fanoutSendEvents();
		fanoutPositionChanges();

		if(time%3==0) {
			Pad.getInstance().repaint();
		}
		WorkspaceManager.getInstance().getWorkingSim().logTime(time);
		StatusBar.getInstance().updateSimulationMode();
		PodLogForm.getInstance().tick();
		StationGlass.getInstance().tick();
	}

	private void fanoutSendEvents() {
		Collection<Future<?>> futures = new LinkedList<Future<?>>();
		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			LineEventPropagator handler=new LineEventPropagator(line);
			futures.add(executor.submit(handler));
		}
		
		for(Future<?> f:futures) {
			try {
				f.get();
			} catch (Exception e) {
				e.printStackTrace();
			}
		}
	}
	
	private void fanoutPositionChanges() {
		Collection<Future<?>> futures = new LinkedList<Future<?>>();
		int time=GlobalTimeKeeper.getInstance().getTime();
		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			PodPositionChanger handler=new PodPositionChanger(line,time);
			futures.add(executor.submit(handler));
		}
		
		for(Future<?> f:futures) {
			try {
				f.get();
			} catch (Exception e) {
				e.printStackTrace();
			}
		}
	}
	
	

	public void stopThread() {
		this.forceStop = true;
	}

	private void generatePassengers(int time) {
		if (time % (10 * WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()) == 0) {
			addLoad(time);
		}
	}

	private void addLoad(int time) {
		SimDataHolder sim = WorkspaceManager.getInstance().getWorkingSim();
		int slot = time / (WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec() * 10);
		if(slot==360) {
			return;
		}
		for (Station st : sts) {
			String r = sim.getLoad().getDestination(st.getId(),slot);
			if (!r.equals(st.getId())) {
				Station end = (Station) WorkspaceManager.getInstance().getNetwork().getNode(r);
				Passenger p = new Passenger(st, end, time);
				WorkspaceManager.getInstance().getWorkingSim().getSummary().logPassengerEntry(p);
				st.addPassenger(p);
			}
		}

		for (Station st : sts) {
			st.putPassengersToPods(time);
		}
	}
}

class LineEventPropagator implements Runnable {

	private Line line;
	public  LineEventPropagator(Line line) {
		this.line=line;
	}
	
	@Override
	public void run() {
		line.propagateEvent();
	}
	
}


class PodPositionChanger implements Runnable {

	private Line line;
	private int time;
	public  PodPositionChanger(Line line, int time) {
		this.line=line;
		this.time=time;
	}
	
	@Override
	public void run() {
		List<Pod> pods = line.getPodQueue().getAll();
		for (Pod pod : pods) {
			if (!pod.isParked()) {
				pod.changePos(time);
				pod.setLastUpdatedTime(time);
			}
		}	
	}
	
}


