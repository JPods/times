package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.event.TableModelListener;
import javax.swing.table.TableModel;

import com.instinct.objects.network.Station;
import com.instinct.objects.simulation.LoadArray;
import com.instinct.service.WorkspaceManager;

public class SlotForm extends JDialog {

	private JTable table;

	private static SlotForm instance = new SlotForm();

	public static SlotForm getInstance() {
		return instance;
	}

	private SlotForm() {
		table = new JTable();
		this.add(BorderLayout.CENTER, new JScrollPane(table));
		table.setAutoResizeMode(JTable.AUTO_RESIZE_OFF);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		this.setSize(1000, 800);
		
		this.setLocationRelativeTo(null);
		this.setTitle("Slot Form");
		
		
		JPanel panelBtn = new JPanel();
		JButton okBtn=new JButton("OK");
		panelBtn.add(okBtn);
		
		okBtn.addActionListener(new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				WorkspaceManager.getInstance().saveFile();
				SlotForm.getInstance().setVisible(false);
			}
		});
		
		this.getContentPane().add(panelBtn, BorderLayout.SOUTH);
	}

	public void display() {
		SlotTableModel load = new SlotTableModel(WorkspaceManager.getInstance().getNetwork().getAllStations(), WorkspaceManager.getInstance().getWorkingSim().getLoad());
		table.setModel(load);
		setVisible(true);
	}
	
	public JTable getTable() {
		return table;
	}

}

class SlotTableModel implements TableModel {
	private LoadArray data;
	private List<String> columns=new ArrayList<String>();
	private List<String> stationOrders=new ArrayList<String>();
	
	public SlotTableModel(Collection<Station> stations, LoadArray data) {
		this.data = data;
		columns.add("Station");
		for(int i=0;i<360;i++) {
			columns.add(i+"");
		}
		
		for(Station st:stations) {
			stationOrders.add(st.getId());
		}
	}

	@Override
	public void addTableModelListener(TableModelListener arg0) {
	}

	@Override
	public Class<?> getColumnClass(int i) {
		return String.class;
	}

	@Override
	public int getColumnCount() {
		return columns.size();
	}

	@Override
	public String getColumnName(int i) {
		return columns.get(i);
	}

	@Override
	public int getRowCount() {
		return stationOrders.size();
	}

	@Override
	public Object getValueAt(int r, int c) {
		if(c==0) {
			return stationOrders.get(r);
		}

		String stId=stationOrders.get(r);
		int  slot=Integer.parseInt(columns.get(c));
		String destId=data.getDestination(stId, slot);
		return destId;
	}

	@Override
	public boolean isCellEditable(int r, int c) {
		return false;
	}

	@Override
	public void removeTableModelListener(TableModelListener arg0) {

	}

	@Override
	public void setValueAt(Object o, int r, int c) {
		String stId=columns.get(r);
		int  slot=Integer.parseInt(columns.get(c));
		String destId=o.toString();
		if(stId.equals(destId.trim())) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Source and Destination can't be same");
			return;
		}
		data.setDestination(stId, slot, destId);
	}

}
