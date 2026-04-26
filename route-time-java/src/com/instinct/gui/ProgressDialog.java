package com.instinct.gui;

import java.awt.Dimension;

import javax.swing.JDialog;
import javax.swing.JProgressBar;

import com.instinct.service.GlobalTimeKeeper;
import com.instinct.service.RouteTableService;
import com.instinct.service.WorkspaceManager;

public class ProgressDialog extends JDialog {

	private JProgressBar bar=new JProgressBar();
	private Simulator sim;
	
	
	public ProgressDialog(Simulator sim) {
		this.sim=sim;
		this.setLocationRelativeTo(null);
		bar.setPreferredSize(new Dimension(400,30));
		this.add(bar);
		bar.setIndeterminate(true);
		bar.setVisible(true);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		
		this.pack();
		this.setTitle("Computing Routing Table...");
	}
	
	public void start() {
		ProgressMonitorThread t=new ProgressMonitorThread(this, sim);
		this.setVisible(true);
		t.start();
		this.setModal(true);
	}
	
	
}


class ProgressMonitorThread extends Thread {
	private ProgressDialog dialog;
	private Simulator sim;
	
	public ProgressMonitorThread(ProgressDialog dialog,Simulator sim) {
		this.dialog=dialog;
		this.sim=sim;
	}
	
	public void run() {
		WorkspaceManager.getInstance().getNetwork().safeKeeping();
		GlobalTimeKeeper.getInstance().reset();
		RouteTableService.getInstance().recompute();
		WorkspaceManager.getInstance().getWorkingSim().initialize();
		WorkspaceManager.getInstance().getWorkingSim().setStartTimeMs(System.currentTimeMillis());
		dialog.setVisible(false);
		sim.start();
		dialog.dispose();
	}
}
