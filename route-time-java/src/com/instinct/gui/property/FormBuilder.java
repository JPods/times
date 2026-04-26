package com.instinct.gui.property;

import java.util.LinkedHashMap;
import java.util.Map;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Station;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.objects.simulation.SimulationSettings;
import com.instinct.service.WorkspaceManager;

public class FormBuilder {

	private static FormBuilder instance = new FormBuilder();

	public static FormBuilder getInstance() {
		return instance;
	}

	public CompositePropertyEditor makeSimulationForm(SimDataHolder cfg) {
		SimulationSettings ss=cfg.getSettings();
		Map<String,AttributeEditor<?>> list = new LinkedHashMap<String,AttributeEditor<?>>();
		AttributeEditor<Integer> maxVelocity = AttributeEditorFactory.buildCombo("Max. Velocity (KMPH)", cfg.getSettings().getMaxVelocityInKMPH(),new Integer[] { 20, 30, 40, 50, 60, 70, 80, 100 });
		maxVelocity.setSelection(ss.getMaxVelocityInKMPH());
		list.put("Max. Velocity (KMPH)",maxVelocity);
		AttributeEditor<Double> acc = AttributeEditorFactory.buildCombo("Acceleration (G)", cfg.getSettings().getAccInG(), new Double[] { 0.5, 0.75,
				1.0 });
		acc.setSelection(ss.getAccInG());
		list.put("Acceleration (G)",acc);
		AttributeEditor<Double> decc = AttributeEditorFactory.buildCombo("Deceleration (G)", cfg.getSettings().getDeccInG(), new Double[] { 0.5, 0.75,
				1.0 });
		decc.setSelection(ss.getDeccInG());
		list.put("Deceleration (G)",decc);
		
		AttributeEditor<Integer> disembarkTime = AttributeEditorFactory.buildInteger("Disembarking time",cfg.getSettings().getDisembarkingTimeInSec(), 30, 10);
		disembarkTime.setSelection(ss.getDisembarkingTimeInSec());
		list.put("Disembarking time",disembarkTime);
		AttributeEditor<Integer> embarkTime = AttributeEditorFactory.buildInteger("Embarking time (sec)", cfg.getSettings().getEmbarkingTimeInSec(),30, 10);
		
		embarkTime.setSelection(ss.getEmbarkingTimeInSec());
		list.put("Embarking time (sec)",embarkTime);
		AttributeEditor<Integer> stationExitTime = AttributeEditorFactory.buildInteger("Station exit time (sec)", cfg.getSettings().getStationExitTimeInSec(), 120, 30);
		stationExitTime.setSelection(ss.getStationExitTimeInSec());
		list.put("Station exit time (sec)",stationExitTime);
		AttributeEditor<Integer> stationEntryTime = AttributeEditorFactory.buildInteger("Station entry time (sec)",cfg.getSettings().getStationEntryTimeInSec(), 120, 30);
		stationEntryTime.setSelection(ss.getStationEntryTimeInSec());
		list.put("Station entry time (sec)",stationEntryTime);
		AttributeEditor<Integer> ticketingTime = AttributeEditorFactory.buildInteger("Ticketing time (sec)",cfg.getSettings().getTicketingTimeInSec(), 60, 10);
		ticketingTime.setSelection(ss.getTicketingTimeInSec());
		list.put("Ticketing time (sec)", ticketingTime);

		AttributeEditor<Integer> podsPerStation = AttributeEditorFactory.buildCombo("JPods per Station", 1, new Integer[] { 2,4,6 });
		podsPerStation.setSelection(ss.getPodsPerStation());
		list.put("Pods per Station",podsPerStation);
		
		AttributeEditor<Integer> timeScale = AttributeEditorFactory.buildCombo("Step Delay (ms)", 0, new Integer[] { 0,1,5,20,50,100,200,1000 });
		timeScale.setSelection(ss.getSlowMotion());
		list.put("Step Delay (ms)",timeScale);

		AttributeEditor<Integer> timeResolution = AttributeEditorFactory.buildCombo("Ticks Per Sec", 9, new Integer[] { 9 });
		timeResolution.setSelection(ss.getTimeResolutionPerSec());
		list.put("Ticks Per Sec",timeResolution);
		
		AttributeEditor<Integer> graceDistance = AttributeEditorFactory.buildCombo("Grace Distance", 9, new Integer[] { 0,5,10,20,50,100,200 });
		graceDistance.setSelection(ss.getGraceDistance());
		list.put("Grace Distance",graceDistance);
		

			
		CompositePropertyEditor editor = new CompositePropertyEditor("Settings", "Simulation Settings", "Ok", list,new SimulationEditAction());
		editor.setModal(true);
		return editor;
	}
	
	public CompositePropertyEditor makeGraphSettingsForm(SimDataHolder cfg) {
		SimulationSettings ss=cfg.getSettings();
		Map<String,AttributeEditor<?>> list = new LinkedHashMap<String,AttributeEditor<?>>();
		
		AttributeEditor<String> jpods = AttributeEditorFactory.buildText("JPods", ss.getJpodBarColor());
		jpods.setSelection(ss.getJpodBarColor());
		list.put("JPods",jpods);

		AttributeEditor<String> car = AttributeEditorFactory.buildText("Car", ss.getCarBarColor());
		car.setSelection(ss.getCarBarColor());
		list.put("Car",car);

		AttributeEditor<String> bus = AttributeEditorFactory.buildText("Bus", ss.getBusBarColor());
		bus.setSelection(ss.getBusBarColor());
		list.put("Bus",bus);

		AttributeEditor<String> train = AttributeEditorFactory.buildText("Train", ss.getTrainBarColor());
		train.setSelection(ss.getTrainBarColor());
		list.put("Train",train);

		
		CompositePropertyEditor editor = new CompositePropertyEditor("Energy Bar Color Settings", "Color Settings", "Ok", list,new BarColorEditAction());
		editor.setModal(true);
		return editor;
	}

	public CompositePropertyEditor makeStationProperty(final Station model) {
		SimDataHolder simData=WorkspaceManager.getInstance().getWorkingSim();

		Map<String,AttributeEditor<?>> list = new LinkedHashMap<String,AttributeEditor<?>>();

		final AttributeEditor<String> lineId = AttributeEditorFactory.buildText("Station Id", model.getId());
		list.put("Station Id",lineId);
		
		final AttributeEditor<String> name = AttributeEditorFactory.buildText("Station Name", model.getName());
		list.put("Station Name",name);

		final AttributeEditor<String> locLat = AttributeEditorFactory.buildText("Location->Lat", ""+model.getLat());
		list.put("Location->Lat",locLat);
		final AttributeEditor<String> locLon = AttributeEditorFactory.buildText("Location->Lon", ""+model.getLon());
		list.put("Location->Lon",locLon);
		
	
		
		
		final AttributeEditor<Double> passengersTravelled= AttributeEditorFactory.buildDouble("Passengers", model.getPodQueue().getTotalPodsExited(), 0, 0);
		list.put("Passengers",passengersTravelled);
		final AttributeEditor<Double> avgTimeSpent = AttributeEditorFactory.buildDouble("Avg Time Spend (sec)", model.getPodQueue().getAvgTimeSpend()/ simData.getSettings().getTimeResolutionPerSec(), 0, 0);
		list.put("Avg Time Spend (sec)",avgTimeSpent);

		CompositePropertyEditor editor = new CompositePropertyEditor("Design and Last Simulation Data", "Station Properties", "Ok", list, new EditAction() {
			
			@Override
			public void doEditMultiple(Map<String, Map<String, AttributeEditor<?>>> editors) {
				
			}
			
			@Override
			public void doEdit(Map<String, AttributeEditor<?>> editors) {
				model.setName(name.getSelection());
				Pad.getInstance().updateUI();
				NetworkTree.getInstance().updateTree();
			}
		});
		editor.setModal(true);
		return editor;
	}

	public CompositePropertyEditor makeLineProperty(Line model) {
		
		SimDataHolder simData=WorkspaceManager.getInstance().getWorkingSim();
		
		
		Map<String,AttributeEditor<?>> list = new LinkedHashMap<String,AttributeEditor<?>>();

		final AttributeEditor<String> lineId = AttributeEditorFactory.buildText("Line Id", model.getId());
		list.put("Line Id",lineId);

		final AttributeEditor<Double> lineLength = AttributeEditorFactory.buildDouble("Line Length", model.getLength(), 0, 0);
		list.put("Line Length",lineLength);

		final AttributeEditor<String> startLocLat = AttributeEditorFactory.buildText("Start->Lat", ""+model.getStart().getLat());
		list.put("Start->Lat",startLocLat);
		final AttributeEditor<String> startLocLon = AttributeEditorFactory.buildText("Start->Lon", ""+model.getStart().getLon());
		list.put("Start->Lon",startLocLon);
		
		final AttributeEditor<String> endLocLat = AttributeEditorFactory.buildText("End->Lat", ""+model.getEnd().getLat());
		list.put("End->Lat",endLocLat);
		final AttributeEditor<String> endLocLon = AttributeEditorFactory.buildText("End->Lon", ""+model.getEnd().getLon());
		list.put("End->Lon",endLocLon);

		
		final AttributeEditor<String> endId = AttributeEditorFactory.buildText("End", "Lat:"+model.getStart().getLat()+", Lon:"+model.getStart().getLon());
		list.put("End",endId);
		
		
		final AttributeEditor<Double> passengersTravelled= AttributeEditorFactory.buildDouble("Passengers", model.getPodQueue().getTotalPodsExited(), 0, 0);
		list.put("Passengers",passengersTravelled);
		final AttributeEditor<Double> avgTimeSpent = AttributeEditorFactory.buildDouble("Avg Time Spend (sec)", model.getPodQueue().getAvgTimeSpend()/ simData.getSettings().getTimeResolutionPerSec(), 0, 0);
		list.put("Avg Time Spend (sec)",avgTimeSpent);

		CompositePropertyEditor editor = new CompositePropertyEditor("Design and Last Simulation Data", "Line Properties", "Ok", list, null);
		editor.setModal(true);
		return editor;
	}

}


class SimulationEditAction implements EditAction {

	@Override
	public void doEdit(Map<String, AttributeEditor<?>> editors) {
		SimDataHolder sim=WorkspaceManager.getInstance().getWorkingSim();
		SimulationSettings cfg=sim.getSettings();
		
		AttributeEditor<Integer> maxVelocity = (AttributeEditor<Integer>) editors.get("Max. Velocity (KMPH)");
		cfg.setMaxVelocityInKMPH(maxVelocity.getSelection());
		AttributeEditor<Double> acc = (AttributeEditor<Double>) editors.get("Acceleration (G)");
		cfg.setAccInG(acc.getSelection());
		AttributeEditor<Double> decc = (AttributeEditor<Double>) editors.get("Deceleration (G)");
		cfg.setDeccInG(decc.getSelection());
		AttributeEditor<Integer> disembarkTime =(AttributeEditor<Integer>)editors.get("Disembarking time");
		cfg.setDisembarkingTimeInSec(disembarkTime.getSelection());
		AttributeEditor<Integer> embarkTime =(AttributeEditor<Integer>) editors.get("Embarking time (sec)");
		cfg.setEmbarkingTimeInSec(embarkTime.getSelection());
		AttributeEditor<Integer> stationExitTime =(AttributeEditor<Integer>) editors.get("Station exit time (sec)");
		cfg.setStationExitTimeInSec(stationExitTime.getSelection());
		AttributeEditor<Integer> stationEntryTime =(AttributeEditor<Integer>) editors.get("Station entry time (sec)");
		cfg.setStationEntryTimeInSec(stationEntryTime.getSelection());
		AttributeEditor<Integer> ticketingTime =(AttributeEditor<Integer>) editors.get("Ticketing time (sec)");
		cfg.setTicketingTimeInSec(ticketingTime.getSelection());
		AttributeEditor<Integer> slowMotion =(AttributeEditor<Integer>) editors.get("Step Delay (ms)");
		cfg.setSlowMotion(slowMotion.getSelection());
		AttributeEditor<Integer> podsPerStation =(AttributeEditor<Integer>) editors.get("Pods per Station");
		cfg.setPodsPerStation(podsPerStation.getSelection());
		AttributeEditor<Integer> ticksPerSec =(AttributeEditor<Integer>) editors.get("Ticks Per Sec");
		cfg.setTimeResolutionPerSec(ticksPerSec.getSelection());
		AttributeEditor<Integer> graceDistance =(AttributeEditor<Integer>) editors.get("Grace Distance");
		cfg.setGraceDistance(graceDistance.getSelection());

		
		try {
			WorkspaceManager.getInstance().saveSimulationSettings(cfg);
			Pad.getInstance().showAlert("Simulation Settings Saved");
		} catch (Exception e) {
			Pad.getInstance().showAlert("Unable to save: "+ e.getMessage());
			e.printStackTrace();
		}
	}

	@Override
	public void doEditMultiple(Map<String, Map<String, AttributeEditor<?>>> editors) {
	}
	
}


class BarColorEditAction implements EditAction {

	@Override
	public void doEdit(Map<String, AttributeEditor<?>> editors) {
		SimDataHolder sim=WorkspaceManager.getInstance().getWorkingSim();
		SimulationSettings cfg=sim.getSettings();
		
		
		AttributeEditor<String> jpods = (AttributeEditor<String>) editors.get("JPods");
		cfg.setJpodBarColor(jpods.getSelection());
		
		AttributeEditor<String> car = (AttributeEditor<String>) editors.get("Car");
        cfg.setCarBarColor(car.getSelection()); 
        
		AttributeEditor<String> bus = (AttributeEditor<String>) editors.get("Bus");
        cfg.setBusBarColor(bus.getSelection());
        
		AttributeEditor<String> train = (AttributeEditor<String>) editors.get("Train");
		cfg.setTrainBarColor(train.getSelection());
		
		try {
			WorkspaceManager.getInstance().saveSimulationSettings(cfg);
			Pad.getInstance().showAlert("Simulation Settings Saved");
		} catch (Exception e) {
			Pad.getInstance().showAlert("Unable to save: "+ e.getMessage());
			e.printStackTrace();
		}
	}

	@Override
	public void doEditMultiple(Map<String, Map<String, AttributeEditor<?>>> editors) {
	}
	
}
