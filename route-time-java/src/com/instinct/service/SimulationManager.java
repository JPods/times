package com.instinct.service;

import javax.swing.JOptionPane;

import com.instinct.gui.MainFrame;
import com.instinct.gui.ProgressDialog;
import com.instinct.gui.Simulator;
import com.instinct.gui.TimeGraph;
import com.instinct.gui.property.CompositePropertyEditor;
import com.instinct.gui.property.FormBuilder;

public class SimulationManager {

	private static SimulationManager instance=new SimulationManager();
	private Simulator simThread;
	
	public static SimulationManager getInstance() {
		return instance;
	}

	
	public void startSimulation() {
		TimeGraph.getInstance().setVisible(false,null);

		
		simThread = new Simulator();
		ProgressDialog pd=new ProgressDialog(simThread);
		pd.start();
	}
	
	public void showSimulationSettingsForm() {
		CompositePropertyEditor editor = FormBuilder.getInstance().makeSimulationForm(WorkspaceManager.getInstance().getWorkingSim());
		editor.setVisible(true);
	}
	
	public boolean checkIfSaved() {
		if(!WorkspaceManager.getInstance().isSaved()) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Please Save the network before simulation", "Network Not saved", JOptionPane.ERROR_MESSAGE);
			return false;
		}
		return true;
	}
	
	public void stopSimulation() {
		if(simThread!=null) {
			simThread.stopThread();
		}
	}
	
	
	public boolean isSimulationRunning() {
		if(simThread!=null  && simThread.isRunning()) {
			return true;
		}
		return false;
	}
	
	

	
}