package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;

import com.instinct.objects.network.CostHolder;
import com.instinct.service.WorkspaceManager;

public class CostEstimateForm extends JDialog {

	private JTable table;

	private static CostEstimateForm instance = new CostEstimateForm();

	public static CostEstimateForm getInstance() {
		return instance;
	}

	private CostEstimateForm() {
		table = new JTable();
		this.add(BorderLayout.CENTER, new JScrollPane(table));
		table.setAutoResizeMode(JTable.AUTO_RESIZE_ALL_COLUMNS);

		this.setSize(900, 600);
		
		this.setLocationRelativeTo(null);
		this.setTitle("Estimation");
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		
		JPanel panelBtn = new JPanel();
		JButton okBtn=new JButton("OK");
		panelBtn.add(okBtn);
		
		okBtn.addActionListener(new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				WorkspaceManager.getInstance().saveFile();
				CostEstimateForm.getInstance().setVisible(false);
			}
		});
		
		this.getContentPane().add(panelBtn, BorderLayout.SOUTH);
	}

	public void display() {
		CostHolder.getInstance().getTotal(WorkspaceManager.getInstance().getNetwork());
		CostTableModel load = new CostTableModel(CostHolder.getInstance());
		table.setModel(load);
		setVisible(true);
	}
	
	public JTable getTable() {
		return table;
	}

}

