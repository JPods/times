package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.util.List;

import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.event.TableModelListener;
import javax.swing.table.DefaultTableCellRenderer;
import javax.swing.table.TableCellRenderer;
import javax.swing.table.TableModel;

import com.instinct.objects.network.Line;
import com.instinct.objects.simulation.LineData;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.objects.simulation.StationData;
import com.instinct.service.WorkspaceManager;

public class ResultForm extends JDialog {
	private static ResultForm instance = new ResultForm();

	private SummaryResult result;
	private JTable stationData;
	private JTable lineData;

	public static ResultForm getInstance() {
		return instance;
	}

	private ResultForm() {
		this.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		this.setTitle("Simulation Result");
		buildUI();
	}

	private void buildUI() {
		result = new SummaryResult();
		JPanel queues = getQueuesStats();
		this.add(BorderLayout.WEST, result);
		this.add(BorderLayout.CENTER, queues);
	}

	private JPanel getQueuesStats() {
		JPanel panel = new JPanel();
		panel.setLayout(new BoxLayout(panel, BoxLayout.Y_AXIS));
		stationData = new JTable();
		JScrollPane scrollPane = new JScrollPane(stationData);
		scrollPane.setPreferredSize(new Dimension(800, 300));
		;
		scrollPane.setBorder(BorderFactory.createTitledBorder("Station data"));
		panel.add(scrollPane);
		lineData = new JTable();

		scrollPane = new JScrollPane(lineData);
		scrollPane.setPreferredSize(new Dimension(500, 300));
		;
		scrollPane.setBorder(BorderFactory.createTitledBorder("Line data"));
		panel.add(scrollPane);

		return panel;
	}

	public void show(SimDataHolder simData) {
		result.setData(simData);
		stationData.setModel(new StationTableModel(simData.getStationsData()));
		List<LineData> lines=simData.getLinesData();
		lineData.setModel(new LineTableModel(lines));
		for(int i=0;i<lineData.getColumnCount();i++) {
			lineData.getColumnModel().getColumn(i).setCellRenderer(new LineTableCellRenderer(lines));
		}
		this.pack();
		setLocationRelativeTo(null);
		this.setVisible(true);
	}

}

class LineTableModel implements TableModel {

	private static final String columnNames[] = new String[] { "ID", "Length", "Start", "End", "Arrived", "left", "Avg. Time" };
	private List<LineData> lines;

	public LineTableModel(List<LineData> lines) {
		this.lines = lines;
	}

	@Override
	public void addTableModelListener(TableModelListener arg0) {
	}

	@Override
	public Class<?> getColumnClass(int i) {
		if (i < 4) {
			return String.class;
		}
		return Integer.class;
	}

	@Override
	public int getColumnCount() {
		return 7;
	}

	@Override
	public String getColumnName(int i) {
		return columnNames[i];
	}

	@Override
	public int getRowCount() {
		return lines.size();
	}

	@Override
	public Object getValueAt(int r, int c) {
		LineData data = lines.get(r);
		Line line = WorkspaceManager.getInstance().getNetwork().getLine(data.getLineId());
		switch (c) {
		case 0: {
			return line.getId();
		}
		case 1: {
			return line.getLength();
		}
		case 2: {
			return data.getStart();
		}
		case 3: {
			return data.getEnd();
		}
		case 4: {
			return data.getStat().getTotalArrived();
		}
		case 5: {
			return data.getStat().getTotalLeft();
		}
		case 6: {
			return data.getStat().getAvgTimeSpent();
		}
		}
		return null;
	}

	@Override
	public boolean isCellEditable(int arg0, int arg1) {
		return false;
	}

	@Override
	public void removeTableModelListener(TableModelListener arg0) {

	}

	@Override
	public void setValueAt(Object arg0, int arg1, int arg2) {

	}
}


class LineTableCellRenderer extends DefaultTableCellRenderer implements TableCellRenderer {

	private  List<LineData> lineData;
	public LineTableCellRenderer( List<LineData> lineData) {
		super();
		this.lineData=lineData;
	}
    @Override
    public Component getTableCellRendererComponent(JTable table, Object value, boolean isSelected, boolean hasFocus, int row, int column) {
        setBackground(null);
        Component c=super.getTableCellRendererComponent(table, value, isSelected, hasFocus, row, column);
        LineData data = lineData.get(row);
		Line line = WorkspaceManager.getInstance().getNetwork().getLine(data.getLineId());
        double fraction=line.computeAvgSpeed()/WorkspaceManager.getInstance().getWorkingSim().getSettings().getMaxVelocityInTU(); //Assuming 100% loaded is passing 1 pod every 3 sec
        Color color=PodPainter.getInstance().interpolate(fraction);
        c.setBackground(color);
        return c;
    }

}



class StationTableModel implements TableModel {

	private static final String columnNames[] = new String[] { "ID", "Coordinate", "Arrived", "left" };
	private List<StationData> data;

	public StationTableModel(List<StationData> data) {
		this.data = data;
	}

	@Override
	public void addTableModelListener(TableModelListener arg0) {
	}

	@Override
	public Class<?> getColumnClass(int i) {
		if (i < 2) {
			return String.class;
		}
		return Integer.class;
	}

	@Override
	public int getColumnCount() {
		return 4;
	}

	@Override
	public String getColumnName(int i) {
		return columnNames[i];
	}

	@Override
	public int getRowCount() {
		return data.size();
	}

	@Override
	public Object getValueAt(int r, int c) {
		StationData stData = data.get(r);
		switch (c) {
		case 0: {
			return stData.getName();
		}
		case 1: {
			return stData.getCoordinate();
		}
		case 2: {
			return stData.getStat().getTotalArrived();
		}
		case 3: {
			return stData.getStat().getTotalLeft();
		}
		}
		return null;
	}

	@Override
	public boolean isCellEditable(int arg0, int arg1) {
		return false;
	}

	@Override
	public void removeTableModelListener(TableModelListener arg0) {

	}

	@Override
	public void setValueAt(Object arg0, int arg1, int arg2) {

	}
}