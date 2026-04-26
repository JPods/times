package com.instinct.gui;

import javax.swing.event.TableModelListener;
import javax.swing.table.TableModel;

import com.instinct.objects.network.CostHolder;
import com.instinct.objects.network.CostItem;
import com.instinct.service.StaticUtil;

public class CostTableModel implements TableModel {

	private CostHolder cost;
	
	private String columns[]={"Item", "Cost", "Unit", "Total"};
	private Class colClass[]={String.class, Double.class, Double.class, Double.class};
	
	private double total;
	
	public CostTableModel(CostHolder cost) {
		this.cost=cost;
		
		total=0;
		for(CostItem ci:cost.getCostItems()) {
			total=total+ci.getTotal();
		}
		total=StaticUtil.round(total/1000000);
	}

	@Override
	public void addTableModelListener(TableModelListener arg0) {
		
	}

	@Override
	public Class<?> getColumnClass(int i) {
		return colClass[i];
	}

	@Override
	public int getColumnCount() {
		return 4;
	}

	@Override
	public String getColumnName(int i) {
		return columns[i];
	}

	@Override
	public int getRowCount() {
		return cost.getCostItems().size()+1;
	}

	@Override
	public Object getValueAt(int r, int c) {
		if(r<cost.getCostItems().size()) {
			CostItem ci=cost.getCostItems().get(r);
			switch(c) {
				case 0: { return ci.getName(); }
				case 1: { return ci.getPrice(); }
				case 2: { return ci.getUnit(); }
				case 3: { return StaticUtil.round(ci.getTotal()); }
			} 
		}
		if(c==0) {
			return "Total in Million USD";
		} else if(c==3) {
			return total;
		}
		
		return null;
	}

	@Override
	public boolean isCellEditable(int r, int c) {
		return false;
	}

	@Override
	public void removeTableModelListener(TableModelListener arg0) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void setValueAt(Object arg0, int arg1, int arg2) {
		// TODO Auto-generated method stub
		
	}
	
	

}
