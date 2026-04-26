package com.instinct.service;

import java.awt.Dimension;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.swing.JDialog;
import javax.swing.JProgressBar;
import javax.swing.SwingWorker;

public class ProgressbarWorker extends SwingWorker<AtomicBoolean, Object> {

	private JProgressBar progressBar = new JProgressBar(0, 100);
	private AtomicBoolean status;
	private Runnable job;
	
	public ProgressbarWorker(AtomicBoolean status, Runnable job) {
		JDialog dialog=new JDialog();
		dialog.setLocationRelativeTo(null);
		dialog.setPreferredSize(new Dimension(200,30));
		dialog.add(progressBar);
		this.status=status;
		status.set(true);
		this.job=job;
		dialog.setVisible(true);
	}
	
	@Override
	protected AtomicBoolean doInBackground() throws Exception {
		job.run();
		return status;
	}

	protected void done() {
        progressBar.setVisible(false);
        status.set(false);
     }
}
