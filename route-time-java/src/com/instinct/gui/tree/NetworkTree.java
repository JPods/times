package com.instinct.gui.tree;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;

import javax.swing.JComponent;
import javax.swing.JMenuItem;
import javax.swing.JPanel;
import javax.swing.JPopupMenu;
import javax.swing.JScrollPane;
import javax.swing.JTree;
import javax.swing.SwingUtilities;
import javax.swing.tree.DefaultMutableTreeNode;
import javax.swing.tree.DefaultTreeCellRenderer;
import javax.swing.tree.DefaultTreeModel;
import javax.swing.tree.TreeNode;
import javax.swing.tree.TreePath;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.widgets.Drawable;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.RenderableObject;
import com.instinct.service.SimResultManager;
import com.instinct.service.WorkspaceManager;

public class NetworkTree extends JPanel implements MouseListener {

	private static NetworkTree instance = new NetworkTree();
	private JTree tree;
	private TreeExpansionManager tem=new TreeExpansionManager();
	
	private NodeGroup highlightedNg;
	private DefaultMutableTreeNode stations;
	private Object lines;
	private DefaultMutableTreeNode switches;
	private Object simulations;
	private DefaultMutableTreeNode root;

	public static NetworkTree getInstance() {
		return instance;
	}

	private NetworkTree() {
		tree = new JTree();
		tree.addMouseListener(this);
		tree.addTreeExpansionListener(tem);
		this.setLayout(new BorderLayout());
		this.add(BorderLayout.CENTER, new JScrollPane(tree));
		tree.setCellRenderer(new NetworkTreeCellRenderer());
		updateTree();

	}

	public void updateTree() {
		DefaultMutableTreeNode root = (DefaultMutableTreeNode) tree.getModel().getRoot();
		root.removeAllChildren();
		addNetwork(WorkspaceManager.getInstance().getNetwork());

		if(root!=null) {
			tree.expandRow(0);
			tree.expandRow(1);
		}
		if(tem.isStationsExpanded()) {
			tree.expandRow(2);
		}
		if(tem.isLinesExpanded()) {
			tree.expandRow(3);
		}
		if(tem.isSwitchesExpanded()) {
			tree.expandRow(4);
		}
		if(tem.isSimulationsExpanded()) {
			tree.expandRow(5);
		}
	}

	private void addNetwork(Network net) {
		
		root = new DefaultMutableTreeNode("Network");
		tree.setModel(new DefaultTreeModel(root));
		
		if(net==null) {
			return;
		}
		DefaultMutableTreeNode netNode = new DefaultMutableTreeNode(net);
		root.add(netNode);
		List sortedSetStations=GUIUtil.sortStations(net.getAllStations());
		stations=addNodeElements("Stations", netNode, sortedSetStations);

		lines=addLineElements("Lines", netNode);

		List sortedSetSwitches=GUIUtil.sortSwitches(net.getAllSwitchs());
		switches=addNodeElements("Switches", netNode, sortedSetSwitches);
	
		simulations=addSimulations("Simulations", netNode);
	}

	private DefaultMutableTreeNode addSimulations(String label, DefaultMutableTreeNode parentNode) {
		List<String> t=new ArrayList<String>((SimResultManager.getInstance().getSimulationsList()));
		Collections.sort(t);
		DefaultMutableTreeNode labelNode = new DefaultMutableTreeNode(label);
		parentNode.add(labelNode);
		for (String s : t) {
			DefaultMutableTreeNode elNode = new DefaultMutableTreeNode(s);
			labelNode.add(elNode);
		}
		return labelNode;
	}

	private DefaultMutableTreeNode addLineElements(String label, DefaultMutableTreeNode parentNode) {
		List<Line> sortedSetLines=GUIUtil.sortLines(WorkspaceManager.getInstance().getNetwork().getAllLines());
		DefaultMutableTreeNode labelNode = new DefaultMutableTreeNode(label);
		parentNode.add(labelNode);
		for (Line n : sortedSetLines) {
			DefaultMutableTreeNode elNode = new DefaultMutableTreeNode(n);
			labelNode.add(elNode);
		}
		return labelNode;
	}

	private DefaultMutableTreeNode addNodeElements(String label, DefaultMutableTreeNode parentNode, Collection<? extends Node> elements) {
		DefaultMutableTreeNode labelNode = new DefaultMutableTreeNode(label);
		parentNode.add(labelNode);
		for (Node n : elements) {
			DefaultMutableTreeNode elNode = new DefaultMutableTreeNode(n);
			labelNode.add(elNode);
		}
		return labelNode;
	}
	

	@Override
	public void mouseClicked(MouseEvent e) {

		TreePath path = tree.getPathForLocation(e.getX(), e.getY());
		if (path == null) {
			return;
		}
		if(this.highlightedNg!=null) {
			this.highlightedNg.setHighlight(false);
			this.highlightedNg=null;
		}
		tree.setSelectionPath(path);
		DefaultMutableTreeNode treeNode=(DefaultMutableTreeNode)path.getLastPathComponent();
		DefaultMutableTreeNode parentNode=(DefaultMutableTreeNode)treeNode.getParent();
		if(treeNode.getUserObject() instanceof RenderableObject<?>) {
			processNodeClick(e, treeNode);
		} else if(parentNode!=null && parentNode.getUserObject().equals("Simulations") && SwingUtilities.isRightMouseButton(e)) {
			JPopupMenu menu=buildMenu(treeNode.getUserObject().toString());
			menu.show(MainFrame.getInstance(), e.getXOnScreen(), e.getYOnScreen());
		}
		Pad.getInstance().updateUI();
	}


	

	private void processNodeClick(MouseEvent e, DefaultMutableTreeNode treeNode) {
		RenderableObject<?> obj = (RenderableObject<?>)treeNode.getUserObject();
		Drawable<?> d=obj.getUI();
		Pad.getInstance().setHighlight(d);
		Pad.getInstance().zoomToHighlight(d);
		if (SwingUtilities.isRightMouseButton(e)) {
			JPopupMenu menu=obj.getPopupMenu();
			menu.show(MainFrame.getInstance(), e.getXOnScreen(), e.getYOnScreen());
		}
	}

	@Override
	public void mouseEntered(MouseEvent arg0) {
		// TODO Auto-generated method stub

	}

	@Override
	public void mouseExited(MouseEvent arg0) {
		// TODO Auto-generated method stub

	}

	@Override
	public void mousePressed(MouseEvent arg0) {
		// TODO Auto-generated method stub

	}

	@Override
	public void mouseReleased(MouseEvent arg0) {
		// TODO Auto-generated method stub

	}

	public void setHighlight(Drawable currentlyHighlighted) {
		DefaultMutableTreeNode root = (DefaultMutableTreeNode) tree.getModel().getRoot();

		Enumeration<TreeNode> en = root.depthFirstEnumeration();
		while (en.hasMoreElements()) {
		  DefaultMutableTreeNode node = (DefaultMutableTreeNode) en.nextElement();
		  if(node.isLeaf() && node.getUserObject() instanceof RenderableObject<?>) {
			  RenderableObject<?> obj = (RenderableObject<?>) node.getUserObject();
				Drawable<?> d=obj.getUI(); 
				if(d==currentlyHighlighted) {
					tree.setSelectionPath(new TreePath(node.getPath()));
					return;
				}
		  }
		}		
	}
	
	private JPopupMenu buildMenu(final String simulationName) {
		JPopupMenu popup = new JPopupMenu();
		ActionListener rotateActionListener=new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				 String cmd=ae.getActionCommand();
				 if(cmd.equals("Load")) {
					 load(simulationName);
				 } else if(cmd.equals("Delete")){
					 delete(simulationName);
				 }
			}
			
		};
		JMenuItem item;
	    popup.add(item = new JMenuItem("Load"));
	    item.addActionListener(rotateActionListener);
	    popup.add(item = new JMenuItem("Delete"));
	    item.addActionListener(rotateActionListener);
	    
	    return popup;
	}

	
	private void delete(String simulationName) {
		SimResultManager.getInstance().deleteSimulation(simulationName);
		
	}

	private void load(String simulationName) {
		try {
			SimResultManager.getInstance().loadSimulation(simulationName);
		} catch (Exception e) {
			e.printStackTrace();
		}
	}
	
	

}

class NetworkTreeCellRenderer extends  DefaultTreeCellRenderer {

	public Component getTreeCellRendererComponent(JTree tree, Object value,boolean selected, boolean expanded, boolean leaf, int row, boolean hasFocus) {
		JComponent c = (JComponent)super.getTreeCellRendererComponent(tree, value, selected, expanded, leaf, row, hasFocus);
		if(NetworkTree.getInstance()!=null) {
			String loadedSim=SimResultManager.getInstance().getLoadedSimulation();
			if(loadedSim!=null && value.toString().equals(loadedSim)) {
				c.setForeground(Color.GREEN);
			}
		}
		return c;
	}
}
