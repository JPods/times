package com.instinct.gui.tree;

import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.util.List;

import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.DefaultListModel;
import javax.swing.JList;
import javax.swing.JPanel;
import javax.swing.JPopupMenu;
import javax.swing.JScrollPane;
import javax.swing.SwingUtilities;

import com.instinct.gui.GUIUtil;
import com.instinct.objects.network.NodeGroup;
import com.instinct.service.WorkspaceManager;

public class NodeGroupsPanel extends JPanel implements MouseListener {

	private static NodeGroupsPanel instance = new NodeGroupsPanel();

	private JList<NodeGroup> list = new JList<NodeGroup>();
	private DefaultListModel<NodeGroup> model = new DefaultListModel<NodeGroup>();

	private NodeGroup highlightedNg;

	public static NodeGroupsPanel getInstance() {
		return instance;
	}

	private NodeGroupsPanel() {
		this.setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
		list.setModel(model);
		this.add(new JScrollPane(list));
		setBorder(BorderFactory.createTitledBorder("Node Groups"));

		list.addMouseListener(this);
		updateGroups();

	}

	public void updateGroups() {
		model.removeAllElements();
		if (WorkspaceManager.getInstance().getNetwork() == null) {
			return;
		}
		List<NodeGroup> sortedGroups = GUIUtil.sortNodeGroups((WorkspaceManager.getInstance().getNetwork().getNonStationGroups()));
		for (NodeGroup ng : sortedGroups) {
			model.addElement(ng);
		}

		this.updateUI();
	}

	@Override
	public void mouseClicked(MouseEvent me) {
		NodeGroup ng = (NodeGroup) list.getSelectedValue();
		if(this.highlightedNg!=null) {
			this.highlightedNg.setHighlight(false);
			this.highlightedNg=null;
			
		}
		if (ng != null) {
			this.highlightedNg = ng;
			ng.setHighlight(true);
			if (SwingUtilities.isRightMouseButton(me)) {
				JPopupMenu menu = ng.getPopupMenu();
				menu.show(this, me.getX(), me.getY());
			}
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
	
	public void unselect() {
		if(this.highlightedNg!=null) {
			this.highlightedNg.setHighlight(false);
			this.highlightedNg=null;
			
		}
	}
}
