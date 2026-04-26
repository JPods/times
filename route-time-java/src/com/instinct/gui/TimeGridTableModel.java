package com.instinct.gui;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

import javax.swing.table.AbstractTableModel;

import com.instinct.objects.network.Station;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.service.WorkspaceManager;


public class TimeGridTableModel extends AbstractTableModel  {
	
	private SimDataHolder data;
	private Map<Integer, Station> order=new HashMap<Integer, Station>();
	public TimeGridTableModel() {
	}
	
	public void setData(SimDataHolder data, Collection<Station> sts) {
		order.clear();
		this.data=data;
		int i=0;
		for(Station st:sts) {
			order.put(i++, st);
		}
	}

	@Override
	public int getColumnCount() {
		return order.size()+1;
	}

	@Override
	public int getRowCount() {
		return order.size();
	}

	@Override
	public Object getValueAt(int i, int j) {
		if(j==0) {
			Station st=order.get(i);
			return st.getId();
		}
		Station src=order.get(i);
		Station end=order.get(j-1);
		double d= data.getAvgTime(src, end);
		int ret=Integer.MAX_VALUE;
		if(d>0) {
			ret=(int) (d/(WorkspaceManager.getInstance().getWorkingSim().getSettings().getTimeResolutionPerSec()));
		}
		return ret;
	}


	@Override
	public Class<?> getColumnClass(int columnIndex) {
		if(columnIndex==0) {
			return String.class;
		}
		return Integer.class;
	}

	@Override
	public String getColumnName(int columnIndex) {
		if(columnIndex==0) {
			return "Station";
		}
		return order.get(columnIndex-1).getId();
	}

	@Override
	public boolean isCellEditable(int rowIndex, int columnIndex) {
		return false;
	}


}
