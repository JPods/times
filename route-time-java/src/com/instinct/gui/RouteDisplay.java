package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.event.WindowEvent;
import java.awt.event.WindowListener;
import java.util.ArrayList;
import java.util.List;

import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JOptionPane;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.ListSelectionModel;
import javax.swing.event.ListSelectionEvent;
import javax.swing.event.ListSelectionListener;
import javax.swing.table.DefaultTableModel;
import javax.swing.table.TableModel;

import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.RenderableObject;
import com.instinct.objects.network.Station;
import com.instinct.service.RouteTableService;
import com.instinct.service.WorkspaceManager;

public class RouteDisplay extends JDialog implements ListSelectionListener, WindowListener {

	private JTable table=null;
	private List<Node> selected;
	public RouteDisplay() throws Exception {
		super.setSize(1200, 600);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		this.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
		TableModel model = getText();
		table=new JTable(model);
		table.setAutoResizeMode(JTable.AUTO_RESIZE_OFF);
		table.getColumnModel().getColumn(0).setPreferredWidth(100);
		table.getColumnModel().getColumn(1).setPreferredWidth(100);
		table.getColumnModel().getColumn(2).setPreferredWidth(900);
		table.getSelectionModel().setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
		table.getSelectionModel().addListSelectionListener(this);
		JScrollPane scroll=new JScrollPane(table);
		this.getContentPane().add(scroll, BorderLayout.CENTER);
		this.setTitle("Routes");
		this.setLocationRelativeTo( MainFrame.getInstance() );
		
		this.addWindowListener(this);
	}

	private TableModel getText() throws Exception {
		RouteTableService.getInstance().recompute();
		DefaultTableModel model=new DefaultTableModel();
		model.addColumn("Start");
		model.addColumn("Destination");
		model.addColumn("Path");
		List<Node> sts = new ArrayList<Node>(GUIUtil.sortStations(WorkspaceManager.getInstance().getNetwork().getAllStations()));
		for (int i = 0; i < sts.size(); i++) {
			for (int j = 0; j < sts.size(); j++) {
				Station src=(Station) sts.get(i);
				Station dest=(Station) sts.get(j);
				if(src.equals(dest)) {
					continue;
				}
				String row[]=new String[3];
				row[0]=src.getId();
				row[1]=dest.getId();
				row[2]=getPathText(src, dest);
				model.addRow(row);
			}
		}
		
		return model;
	}

	private String getPathText(Station src, Station dest) throws Exception {
		StringBuilder sb=new StringBuilder();
		List<Node> path = RouteTableService.getInstance().getPathNodes(src, dest);
		if(path==null) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Incomplete Network, No route from Station :"+src.getId()+" to Station :"+dest.getId());
			throw new Exception("Incomplete Network");
		}
		
		for (Node n : path) {
            sb.append(n.getId());
			sb.append(", ");
		}
		
		return sb.toString();
	}

	@Override
	public void valueChanged(ListSelectionEvent le) {
		int row=table.getSelectedRow();
		if(row<0) {
			return;
		}
		String srcId=(String) table.getValueAt(row, 0);
		String endId=(String) table.getValueAt(row, 1);
		
		Station src=(Station)WorkspaceManager.getInstance().getNetwork().getNode(srcId);
		Station end=(Station)WorkspaceManager.getInstance().getNetwork().getNode(endId);
		List<Node> path = RouteTableService.getInstance().getPathNodes(src, end);
		
		setHighlighting(selected,false);		
		setHighlighting(path,true);		
		
		this.selected=path;
		Pad.getInstance().updateUI();
		
	}

	private void setHighlighting(List<Node> path, boolean highlight) {
		if(path==null) {
			return;
		}
		for(int i=0;i<path.size();i++) {
			Node n=path.get(i);
			if(n instanceof RenderableObject<?>) {
				Drawable<?> d=((RenderableObject<?>)n).getUI();
				d.setHighlight(highlight);
			}
			
			if(i<path.size()-1) {
				Node e=path.get(i+1);
				Line line=WorkspaceManager.getInstance().getNetwork().getLine(n, e);
				line.getUI().setHighlight(highlight);

			}
		}
	}

	@Override
	public void windowActivated(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void windowClosed(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void windowClosing(WindowEvent we) {
		setHighlighting(selected, false);
		Pad.getInstance().updateUI();
	}

	@Override
	public void windowDeactivated(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void windowDeiconified(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void windowIconified(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}

	@Override
	public void windowOpened(WindowEvent e) {
		// TODO Auto-generated method stub
		
	}
}



