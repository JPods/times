package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Dimension;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.List;

import javax.swing.JButton;
import javax.swing.JComboBox;
import javax.swing.JDialog;
import javax.swing.JPanel;

import com.instinct.objects.network.Station;
import com.instinct.service.WorkspaceManager;

public class StationGlass extends JDialog implements ActionListener {

	private JComboBox<Station> combo = new JComboBox<Station>();
	private StationGlassPane area = new StationGlassPane();
	private boolean isVisible;
	private JButton select = new JButton("Select");
	private JButton ok = new JButton("OK");

	private static StationGlass instance = new StationGlass();
	
	

	private StationGlass() {
		super();
		this.getContentPane().setLayout(new BorderLayout());
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		JPanel panelTop = new JPanel();
		panelTop.add(combo);
		panelTop.add(select);
		select.addActionListener(this);
		this.getContentPane().add(panelTop, BorderLayout.NORTH);
		area.setPreferredSize(new Dimension(600, 200));
		this.getContentPane().add(area, BorderLayout.CENTER);

		JPanel panelBelow = new JPanel();
		panelBelow.add(ok);
		this.getContentPane().add(panelBelow, BorderLayout.SOUTH);
		ok.addActionListener(new ActionListener() {

			@Override
			public void actionPerformed(ActionEvent arg0) {
				isVisible = false;
				StationGlass.getInstance().setVisible(false);
			}
		});



		this.pack();
		this.setLocationRelativeTo(null);
		this.setTitle("Station Glass");

	}

	public static StationGlass getInstance() {
		return instance;
	}


	public void tick() {
		if (!isVisible) {
			return;
		}

		area.updateUI();
	}


	
	


	public void display() {
		isVisible = true;
		combo.removeAllItems();
		List sortedSetStations=GUIUtil.sortStations(WorkspaceManager.getInstance().getNetwork().getAllStations());

		for (Object st : sortedSetStations) {
			combo.addItem((Station)st);
		}
		setVisible(true);

	}


	@Override
	public void actionPerformed(ActionEvent e) {
		Station st= (Station) combo.getSelectedItem();
		if (st == null) {
			return;
		}

		area.setStation(st);
		area.updateUI();
	}

	public void setStationSelected(Station station) {
		combo.setSelectedItem(station);
		area.setStation(station);
		area.updateUI();
		
	}
}
