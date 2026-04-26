package com.instinct.objects.network;

import java.util.ArrayList;
import java.util.List;

import com.instinct.config.Config;

public class CostHolder {

	private int podCost=17142;
	private int lineCostPerMeter=1500;
	private int stationCost=152914;
	private int switchCost=5532;
	private int sensorsPerMeter=50;
	private int solarKwPerKm=100;
	private int solarKwCost=1000;
	private int otherCostPerKm=500000;
	
	private List<CostItem> costItems=new ArrayList<CostItem>();
	
	
	private static CostHolder instance=new CostHolder();
	
	public static CostHolder getInstance() {
		return instance;
	}
	
	private CostHolder() {
		
	}
	
	public double getTotal(Network net) {
		if(net==null) {
			return 0;
		}
		costItems.clear();

		int lengthInMeter=(int)net.getTotalLineLength();
		int lengthInKm=(int)(net.getTotalLineLength()/1000);
		costItems.add(new CostItem("Line Cost/Meter", lineCostPerMeter, lengthInMeter));
		costItems.add(new CostItem("Sensors Cost/Meter", sensorsPerMeter,lengthInMeter));
		costItems.add(new CostItem("Solar-Plant Cost/KW @ "+solarKwPerKm+" Kw/Km", solarKwCost, lengthInKm*solarKwPerKm));
		costItems.add(new CostItem("Pods @ "+Config.getInstance().getPodsPerKm()+" Pods/Km", podCost, lengthInKm*Config.getInstance().getPodsPerKm()));
		costItems.add(new CostItem("Stations", stationCost, net.getAllStations().size()));
		costItems.add(new CostItem("Switches", switchCost, net.getAllConvergences().size()+net.getAllDivergences().size()));
		costItems.add(new CostItem("Miscellany Cost/Km", otherCostPerKm, lengthInKm));
		
		double total=0;
		for(CostItem ci:costItems) {
			total=total+ci.getTotal();
		}
		
		return total;
	}

	public List<CostItem> getCostItems() {
		return costItems;
	}
	
	
	
}
