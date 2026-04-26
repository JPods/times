package com.instinct.test;

import java.awt.BorderLayout;
import java.awt.event.ItemEvent;
import java.awt.event.ItemListener;

import javax.swing.JComboBox;
import javax.swing.JFrame;
import javax.swing.JScrollPane;
import javax.swing.JTable;

public class ResizeTable {
	  public static void main(String args[]) {

	    final Object rowData[][] = { 
	        { "1", "one",  "I" },
	        { "2", "two",  "II" },
	        { "3", "three", "III" }};
	    final String columnNames[] = { "#", "English", "Roman" };

	    final JTable table = new JTable(rowData, columnNames);
	    JScrollPane scrollPane = new JScrollPane(table);

	    String modes[] = { "Resize All Columns", "Resize Last Column", "Resize Next Column",
	        "Resize Off", "Resize Subsequent Columns" };
	    
	    final int modeKey[] = { JTable.AUTO_RESIZE_ALL_COLUMNS, JTable.AUTO_RESIZE_LAST_COLUMN,
	        JTable.AUTO_RESIZE_NEXT_COLUMN, JTable.AUTO_RESIZE_OFF,
	        JTable.AUTO_RESIZE_SUBSEQUENT_COLUMNS };
	    
	    JComboBox resizeModeComboBox = new JComboBox(modes);

	    ItemListener itemListener = new ItemListener() {
	      public void itemStateChanged(ItemEvent e) {
	        JComboBox source = (JComboBox) e.getSource();
	        int index = source.getSelectedIndex();
	        table.setAutoResizeMode(modeKey[index]);
	      }
	    };
	    resizeModeComboBox.addItemListener(itemListener);

	    JFrame frame = new JFrame("Resizing Table");
	    frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);

	    frame.add(resizeModeComboBox, BorderLayout.NORTH);
	    frame.add(scrollPane, BorderLayout.CENTER);

	    frame.setSize(300, 150);
	    frame.setVisible(true);

	  }
	}