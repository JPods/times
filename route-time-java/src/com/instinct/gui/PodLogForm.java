package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.util.HashMap;
import java.util.Map;

import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.JTextField;

import com.instinct.objects.network.Line;
import com.instinct.objects.network.PodQueue;
import com.instinct.objects.network.Station;
import com.instinct.objects.pod.Pod;
import com.instinct.service.WorkspaceManager;

public class PodLogForm extends JDialog implements ActionListener {

	private Map<String, Pod> allPods = new HashMap<String, Pod>();
	private JTextField idField = new JTextField();
	private JTextArea area = new JTextArea();
	private boolean isVisible;
	private JButton select = new JButton("Select");
	private JButton lock = new JButton("Lock");
	private JButton ok = new JButton("OK");
	private Pod pod;
	private int lastTick;
	private boolean isLocked;
	private static PodLogForm instance = new PodLogForm();

	private PodLogForm() {
		super();
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		idField.setPreferredSize(new Dimension(100,25));
		this.getContentPane().setLayout(new BorderLayout());
		JPanel panelTop = new JPanel();
		panelTop.add(idField);
		panelTop.add(select);
		panelTop.add(lock);
		lock.addActionListener(new ActionListener() {

			@Override
			public void actionPerformed(ActionEvent ae) {
				isLocked = true;
			}
		});
		select.addActionListener(this);
		this.getContentPane().add(panelTop, BorderLayout.NORTH);
		JScrollPane scroll = new JScrollPane(area);
		scroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_ALWAYS);
		scroll.setPreferredSize(new Dimension(1200, 600));
		this.getContentPane().add(scroll, BorderLayout.CENTER);

		JPanel panelBelow = new JPanel();
		panelBelow.add(ok);
		this.getContentPane().add(panelBelow, BorderLayout.SOUTH);
		ok.addActionListener(new ActionListener() {

			@Override
			public void actionPerformed(ActionEvent arg0) {
				isVisible = false;
				if(pod!=null) {
					pod.setGlow(false);
				}
				pod = null;
				lastTick = 0;
				PodLogForm.getInstance().setVisible(false);
			}
		});



		this.setPreferredSize(new Dimension(1260, 680));
		this.pack();
		this.setLocationRelativeTo(null);
		this.setTitle("Pod Log");

        area.setEnabled(false);
        area.setDisabledTextColor(Color.BLACK);
        
	}

	public static PodLogForm getInstance() {
		return instance;
	}

	public void tick() {
		if (!isVisible || isLocked) {
			return;
		}

		updateList();
	}

	private void updateList() {
		if (pod == null || pod.getLastUpdatedTime() <= lastTick) {
			return;
		}
		lastTick = pod.getLastUpdatedTime();
		String as = pod.getEvents().getLastAdded().getHistory();
		String text=area.getText();
		int len=text.length();
		
		if(len>1024*1024*1) {
			area.setText("#################################  ROLLING OVER ##############################");
		}
		text = as.toString() + "\n" + area.getText();
		area.setText(text);
	}

	public void display() {
		isVisible = true;
		area.setText("");
		lastTick = 0;
		for (Line line : WorkspaceManager.getInstance().getNetwork().getAllLines()) {
			addPodQueue(line.getPodQueue());
		}

		for (Station st : WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			addPodQueue(st.getPodQueue());
		}

		setVisible(true);

	}

	private void addPodQueue(PodQueue q) {
		for (Pod pod : q.getAll()) {
			allPods.put(pod.getId(), pod);
		}
	}

	@Override
	public void actionPerformed(ActionEvent e) {
		if(this.pod!=null) {
			pod.setGlow(false);
		}
		isLocked = false;
		String id = (String) idField.getText().trim();
		if (id == null) {
			return;
		}

		this.pod = allPods.get(id);
		this.pod.setGlow(true);
        this.addWindowListener(new CustomWindowListener(pod));
	}

}

	
	class CustomWindowListener extends WindowAdapter {

		private Pod pod;
		
		public CustomWindowListener(Pod pod) {
			this.pod=pod;
		}
		
		@Override
		public void windowClosed(WindowEvent arg0) {
			pod.setGlow(false);
		}

		@Override
		public void windowClosing(WindowEvent arg0) {
			pod.setGlow(false);
		}
		
	}

