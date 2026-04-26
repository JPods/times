package com.instinct.gui;

import java.util.HashMap;
import java.util.Map;

import javax.swing.BoxLayout;
import javax.swing.JPanel;

import com.instinct.gui.property.PropertyGroupPanel;
import com.instinct.objects.network.Network;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.service.StaticUtil;
import com.instinct.service.WorkspaceManager;

public class SummaryResult extends JPanel {



	
	public void setData(SimDataHolder sim) {
		this.removeAll();
		this.setLayout(new BoxLayout(this,BoxLayout.Y_AXIS));

		Map<String, String> props = new HashMap<String, String>();
		props.put("Carried", GUIUtil.format6(sim.getSummary().getPassengersCarried()));
		props.put("Travelling", GUIUtil.format4(sim.getSummary().getPassengersTraveling()));
		props.put("Waiting", GUIUtil.format4(sim.getSummary().getPassengersWaiting()));
		props.put("Throughput", GUIUtil.format4(sim.getThroughputPerHour()));
		PropertyGroupPanel p1=new PropertyGroupPanel("Capacity", props);
		this.add(p1);
		
		props.clear();
		props.put("Avg", GUIUtil.format22(sim.getSummary().getAvgVelocityInKMPH()));
		props.put("Slowest", GUIUtil.format22(sim.getSummary().getSlowestVelocityInKMPH()));
		PropertyGroupPanel p2=new PropertyGroupPanel("Velocity (KMPH)", props);
		this.add(p2);

		props.clear();
		props.put("Avg", GUIUtil.format42(sim.getSummary().getAvgTripTimeInMin()));
		props.put("Longest", GUIUtil.format42(sim.getSummary().getLongestTripTimeInMin()));
		props.put("Longest Waiting", GUIUtil.format42(sim.getSummary().getLongestWaitingTimeInMin()));
		PropertyGroupPanel p3=new PropertyGroupPanel("Timings (Min)", props);
		this.add(p3);

		props.clear();
		props.put("Avg", GUIUtil.format42(sim.getSummary().getAvgTripDistanceInKM()));
		props.put("Total", GUIUtil.format6(sim.getSummary().getTotalTripDistanceInKM()));
		PropertyGroupPanel p4=new PropertyGroupPanel("Distance (KM)", props);
		this.add(p4);

		props.clear();
		props.put("Simulated Time", sim.getTimeElapsedInHrMmSs());
		props.put("Machine Time", sim.getTimeElapsedInHrMmSsComputer());
		PropertyGroupPanel p5=new PropertyGroupPanel("Run", props);
		this.add(p5);

		Network n = WorkspaceManager.getInstance().getNetwork();
		props.clear();
		props.put("No of Stations", n.getAllStations().size() + "");
		props.put("No of Node Groups", n.getNumberOfNodeGroups() + "");
		
		int fixedPods=n.getAllStations().size()*WorkspaceManager.getInstance().getWorkingSim().getSettings().getPodsPerStation();
		int variablePods=WorkspaceManager.getInstance().getNetwork().getTotalPods();
		props.put("No of Pods",(fixedPods+variablePods)+ "");
		PropertyGroupPanel p6=new PropertyGroupPanel("Network", props);
		this.add(p6);

		props.clear();
		props.put("No of Switches", n.getAllSwitchs().size() + "");
		props.put("No of Convergences", n.getAllConvergences().size() + "");
		props.put("No of Divergences", n.getAllDivergences().size() + "");
		PropertyGroupPanel p7=new PropertyGroupPanel("Switches", props);
		this.add(p7);

		props.clear();
		props.put("No of Lines", n.getAllLines().size() + "");
		props.put("Length (KM)", StaticUtil.round(n.getTotalLineLength() / 1000) + "");
		PropertyGroupPanel p8=new PropertyGroupPanel("Lines", props);
		this.add(p8);
		
		
		props.clear();
		props.put("File path", WorkspaceManager.getInstance().getCurrentlySelectedFile());
		PropertyGroupPanel p9=new PropertyGroupPanel("General", props);
		this.add(p9);
		
		
	}
	

}
