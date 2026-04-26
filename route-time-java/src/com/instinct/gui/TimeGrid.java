package com.instinct.gui;

import java.awt.BorderLayout;

import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.table.TableColumn;
import javax.swing.table.TableColumnModel;

import com.instinct.objects.network.Network;
import com.instinct.service.WorkspaceManager;

public class TimeGrid extends JDialog {
	private static TimeGrid instance = new TimeGrid();
	private JTable table = null;

	public static TimeGrid getInstance() {
		instance.init();

		return instance;
	}

	private TimeGrid() {
		super.setSize(600, 620);
		setLocationRelativeTo(null);
		this.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
		this.setTitle("Route Timings between stations");
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());

		JPanel topPanel = new JPanel();
		topPanel.setLayout(new BorderLayout());
		getContentPane().add(topPanel);

		// Create a new table instance
		table = new JTable();
		init();
		table.setDefaultRenderer(Integer.class, new TimeGridCellRenderer());
		// Add the table to a scrolling pane
		JScrollPane scrollPane = new JScrollPane(table);
		topPanel.add(scrollPane, BorderLayout.CENTER);
	}

	private void init() {
		TimeGridTableModel tableModel = new TimeGridTableModel();
		Network net = WorkspaceManager.getInstance().getNetwork();
		tableModel.setData(WorkspaceManager.getInstance().getWorkingSim(), net.getAllStations());
		table.setModel(tableModel);
		table.setAutoResizeMode(JTable.AUTO_RESIZE_OFF);
		TableColumnModel columnModel = table.getColumnModel();
		for (int col = 0; col < columnModel.getColumnCount(); col++) {
			TableColumn tableColumn = columnModel.getColumn(col);
			tableColumn.setPreferredWidth(60);
		}
	}
}