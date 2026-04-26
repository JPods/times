package com.instinct.service;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Collection;
import java.util.HashSet;
import java.util.Set;

import javax.swing.JOptionPane;

import com.google.gson.Gson;
import com.instinct.gui.MainFrame;
import com.instinct.gui.StatusBar;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.objects.simulation.TimeGridData;
import com.instinct.objects.simulation.TimeGridJson;

public class SimResultManager {

	private static SimResultManager instance=new SimResultManager();
	
	private String loadedSimulation;

	private boolean isSimulationListLoaded;
	
	private Collection<String> listOfSimulations;


	private SimDataHolder workingSim;
	
	public static SimResultManager getInstance() {
		return instance;
	}
	

	
	public 	Set<String> getSimulations() {
		return null;
	}
	
	public void saveSimulation() throws Exception {
		String simulationName = JOptionPane.showInputDialog(MainFrame.getInstance(), "Save Simulation As");
		if (WorkspaceManager.getInstance().getCurrentNetworkDirectory().exists() == false) {
			WorkspaceManager.getInstance().getCurrentNetworkDirectory().mkdir();
		}
		String resultDataFile = WorkspaceManager.getInstance().getCurrentNetworkDirectory().getAbsolutePath()+"/"+simulationName+".res";
		saveResult(new File(resultDataFile));
		this.loadedSimulation = simulationName;
		this.listOfSimulations.add(simulationName);
		NetworkTree.getInstance().updateTree();
	}
	
	public Collection<String> getSimulationsList() {
		if(this.isSimulationListLoaded) {
			return listOfSimulations;
		} else {
			loadListOfSimulations();
		}
		return listOfSimulations;
	}

	private void loadListOfSimulations() {
		this.listOfSimulations = new HashSet<String>();
		if (WorkspaceManager.getInstance().getCurrentNetworkDirectory() == null) {
			return;
		}
		File file = new File(WorkspaceManager.getInstance().getCurrentNetworkDirectory().getAbsolutePath());

		if (file.exists() == false) {
			return;
		}

		for (File s : file.listFiles()) {
			if (s.getName().endsWith(".res")) {
				listOfSimulations.add(s.getName().replace(".res",""));
			}
		}
		this.isSimulationListLoaded=true;
	}

	public void deleteSimulation(String simulationName) {
		String fullFilePath = WorkspaceManager.getInstance().getCurrentNetworkDirectory().getAbsolutePath()+"/"+ simulationName+".res";
		File file = new File(fullFilePath);
		file.delete();
		listOfSimulations.remove(simulationName);
		NetworkTree.getInstance().updateTree();
	}


	public void loadSimulation(String simulationName) throws IOException {
		String filePath = WorkspaceManager.getInstance().getCurrentNetworkDirectory().getAbsolutePath() + "/" + simulationName+".res";
		String content = new String(Files.readAllBytes(Paths.get(filePath)));
		TimeGridJson json = TimeGridJson.fromJson(content);
		TimeGridData tgd = new TimeGridData(json);
		long simVersion=Long.parseLong(json.getNetworkVersion());
		if (WorkspaceManager.getInstance().getNetwork().getVersionId()>simVersion) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Network has changed. The old result is no longer valid");
		} else {
			this.workingSim = new SimDataHolder();
			workingSim.setTime(tgd);
			workingSim.setSummary(json.getSummary());
			workingSim.setLinesData(json.getLineData());
			workingSim.setStationsData(json.getStationData());
			workingSim.setSettings(json.getSettings());
			workingSim.setLoad(json.getLoadArray());
			workingSim.setCompleted(true);
			this.loadedSimulation = simulationName;
			WorkspaceManager.getInstance().setWorkingSim(workingSim);
			StatusBar.getInstance().updateSimulationMode();
		} 
	}
	
	private void saveResult(File file) throws IOException {
		TimeGridData grid = WorkspaceManager.getInstance().getWorkingSim().getTimes();
		if (grid == null) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "No result to save");
			return;
		}
		SimDataHolder simData=WorkspaceManager.getInstance().getWorkingSim();
		TimeGridJson json = new TimeGridJson(simData, WorkspaceManager.getInstance().getNetwork().getVersionId()+"");

		// if file doesn't exist, then create it
		if (!file.exists()) {
			file.createNewFile();
		}

		FileWriter fw = new FileWriter(file.getAbsoluteFile());
		BufferedWriter bw = new BufferedWriter(fw);
		Gson gson=new Gson();
		bw.write(gson.toJson(json));
		bw.close();

	}

	public String getLoadedSimulation() {
		return loadedSimulation;
	}
	
}