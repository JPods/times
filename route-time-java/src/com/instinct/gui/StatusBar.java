package com.instinct.gui;

import java.awt.FlowLayout;

import javax.swing.BorderFactory;
import javax.swing.JPanel;

import com.instinct.gui.property.PropertyPanel;
import com.instinct.objects.network.Network;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.service.StaticUtil;
import com.instinct.service.WorkspaceManager;

public class StatusBar extends JPanel  {

	private DesignBar designBar = new DesignBar();
	private SimulationBar simBar = new SimulationBar();
	private JPanel mainBar=new JPanel();
	
	private static StatusBar instance = new StatusBar();
	
	

	public static StatusBar getInstance() {
		return instance;
	}

	private StatusBar() {
		this.setBorder(BorderFactory.createLoweredBevelBorder());
		WrapLayout layout=new WrapLayout(FlowLayout.LEFT);
		this.setLayout(layout);
		designMode();

	}

	
	

	public void designMode() {
		this.removeAll();
		this.add(designBar);
		Network n = WorkspaceManager.getInstance().getNetwork();
		if(n==null) {
			return;
		}
		updateDesignMode();
		this.updateUI();
	}

	public void updateDesignMode() {
		Network n = WorkspaceManager.getInstance().getNetwork();

		designBar.setStations(n.getAllStations().size());
		designBar.setNodeGroups(n.getNumberOfNodeGroups());
		designBar.setSwitches(n.getAllSwitchs().size());
		designBar.setConvergences(n.getAllConvergences().size());
		designBar.setDivergences(n.getAllDivergences().size());
		designBar.setLines(n.getAllLines().size());
		designBar.setLength(StaticUtil.round(n.getTotalLineLength()/ 1000));
	}

	public void simulateMode() {
		this.removeAll();
		this.add(simBar);
		updateSimulationMode();
		this.updateUI();
		this.updateUI();
	}

	public void updateSimulationMode() {
		SimDataHolder sim = WorkspaceManager.getInstance().getWorkingSim();
		if(sim==null) {
			return;
		}
		simBar.update(sim);
	}
}

class DesignBar extends JPanel {
	PropertyPanel numberOfStations=new PropertyPanel("Stations", 0+""); 
	PropertyPanel numberOfNodeGroups=new PropertyPanel("Node Groups", 0+"");
	PropertyPanel numberOfSwitches=new PropertyPanel("Switches", 0+""); 
	PropertyPanel numberOfDivergences=new PropertyPanel("Divergences", 0+""); 
	PropertyPanel numberOfConvergences=new PropertyPanel("Convergences", 0+""); 
	PropertyPanel numberOfLines=new PropertyPanel("Line Segments", 0+""); 
	PropertyPanel totalLength=new PropertyPanel("Length (KM)", 0+""); 

	public DesignBar() {
		this.add(numberOfStations);
		this.add(numberOfNodeGroups);
		this.add(numberOfSwitches);
		this.add(numberOfDivergences);
		this.add(numberOfConvergences);
		this.add(numberOfLines);
		this.add(totalLength);
	}
	


	public void setStations(int stations) {
		numberOfStations.setValue(stations+"");
	}

	public void setNodeGroups(int nodeGroups) {
		numberOfNodeGroups.setValue(nodeGroups+"");
	}

	public void setDivergences(int divergences) {
		numberOfDivergences.setValue(divergences+"");
	}

	public void setConvergences(int convergences) {
		numberOfConvergences.setValue(convergences+"");
	}

	public void setLines(int lines) {
		numberOfLines.setValue(lines+"");
	}

	public void setLength(double length) {
		totalLength.setValue(length+"");
	}
	
	public void setSwitches(int switches) {
		numberOfSwitches.setValue(switches+"");
	}
}


class SimulationBar extends JPanel {
	SimDataHolder sim = WorkspaceManager.getInstance().getWorkingSim();
	PropertyPanel carried=new PropertyPanel("Carried",GUIUtil.format6(sim.getSummary().getPassengersCarried()));
	PropertyPanel travelling=new PropertyPanel("Travelling", GUIUtil.format6(sim.getSummary().getPassengersTraveling()));
	PropertyPanel waiting=new PropertyPanel("Waiting", GUIUtil.format4(sim.getSummary().getPassengersWaiting()));
	PropertyPanel throughput=new PropertyPanel("Throughput", GUIUtil.format6(sim.getThroughputPerHour()));

	PropertyPanel avgTrip=new PropertyPanel("Avg Velocity(KMPH)", GUIUtil.format22(sim.getSummary().getAvgVelocityInKMPH()));
	PropertyPanel slowest=new PropertyPanel("Slowest Velocity(KMPH)", GUIUtil.format22(sim.getSummary().getSlowestVelocityInKMPH()));
	PropertyPanel avgTime=new PropertyPanel("Avg Time(min)", GUIUtil.format42(sim.getSummary().getAvgTripTimeInMin()));
	PropertyPanel longest=new PropertyPanel("Longest Time(min)", GUIUtil.format42(sim.getSummary().getLongestTripTimeInMin()));
	PropertyPanel longestWaiting=new PropertyPanel("Longest Waiting (min)", GUIUtil.format42(sim.getSummary().getLongestWaitingTimeInMin()));

	PropertyPanel avgDistance=new PropertyPanel("Avg Distance(KM)", GUIUtil.format42(sim.getSummary().getAvgTripDistanceInKM()));
	PropertyPanel totalDistance=new PropertyPanel("Total Distance(KM)", GUIUtil.format6(sim.getSummary().getTotalTripDistanceInKM()));
	
	PropertyPanel tick=new PropertyPanel("Tick", sim.getTick()+"");
	PropertyPanel simulatedTime=new PropertyPanel("Simulated Time", sim.getTimeElapsedInHrMmSs());
	PropertyPanel systemTime=new PropertyPanel("Real Time", sim.getTimeElapsedInHrMmSsComputer());

	public SimulationBar() {
		WrapLayout layout=new WrapLayout(FlowLayout.LEFT);
		this.setLayout(layout);
		this.add(carried);
		this.add(travelling);
		this.add(waiting);
		this.add(throughput);
		
		this.add(avgTrip);
		this.add(slowest);
		this.add(avgTime);
		this.add(longest);
		this.add(longestWaiting);

		this.add(avgDistance);
		this.add(totalDistance);

		this.add(tick);
		this.add(simulatedTime);
		this.add(systemTime);
	}
	
	
	public void update(SimDataHolder sim) {
		carried.setValue((GUIUtil.format6(sim.getSummary().getPassengersCarried())));
		travelling.setValue(GUIUtil.format6(sim.getSummary().getPassengersTraveling()));
		waiting.setValue(GUIUtil.format6(sim.getSummary().getPassengersWaiting()));
		throughput.setValue(GUIUtil.format6(sim.getThroughputPerHour()));

		avgTrip.setValue(GUIUtil.format22(sim.getSummary().getAvgVelocityInKMPH()));
		slowest.setValue(GUIUtil.format22(sim.getSummary().getSlowestVelocityInKMPH()));
		avgTime.setValue(GUIUtil.format42(sim.getSummary().getAvgTripTimeInMin()));
		longest.setValue(GUIUtil.format42(sim.getSummary().getLongestTripTimeInMin()));
		longestWaiting.setValue(GUIUtil.format42(sim.getSummary().getLongestWaitingTimeInMin()));

		avgDistance.setValue(GUIUtil.format42(sim.getSummary().getAvgTripDistanceInKM()));
		totalDistance.setValue(GUIUtil.format6(sim.getSummary().getTotalTripDistanceInKM()));
		
		tick.setValue(sim.getTick()+"");
		simulatedTime.setValue(sim.getTimeElapsedInHrMmSs());
		systemTime.setValue(sim.getTimeElapsedInHrMmSsComputer());
	}
	
}

