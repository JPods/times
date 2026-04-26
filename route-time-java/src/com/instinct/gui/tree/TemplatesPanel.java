package com.instinct.gui.tree;

import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;

import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.DefaultListModel;
import javax.swing.JList;
import javax.swing.JMenuItem;
import javax.swing.JPanel;
import javax.swing.JPopupMenu;
import javax.swing.JScrollPane;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;
import javax.swing.event.ListSelectionEvent;
import javax.swing.event.ListSelectionListener;

import com.instinct.gui.pad.Pad;
import com.instinct.service.ActionManager;
import com.instinct.service.TemplateManager;
import com.instinct.service.actions.ActionFactoryBuilder;

public class TemplatesPanel extends JPanel implements MouseListener {

	private static TemplatesPanel instance = new TemplatesPanel();

	private JList<String> list = new JList<String>();
	private DefaultListModel<String> model = new DefaultListModel<String>();

	private JPopupMenu popup;

	public static TemplatesPanel getInstance() {
		return instance;
	}

	private TemplatesPanel() {
		this.setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
		list.setModel(model);
		this.add(new JScrollPane(list));
		setBorder(BorderFactory.createTitledBorder("Templates. "+TemplateManager.getInstance().getTemplateDir()));

		list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
		list.addListSelectionListener(new ListSelectionListener() {

			@Override
			public void valueChanged(ListSelectionEvent e) {
				String selectedItem = list.getSelectedValue();
				if (selectedItem != null && selectedItem.trim().length() > 0) {
					Pad.getInstance().setCursorImage("template.png");
					ActionManager.getInstance().setActionFactory(ActionFactoryBuilder.getInstance().getTemplateAddFac(list.getSelectedValue()));
					list.setToolTipText("Template Selected is:"+list.getSelectedValue());
				}
			}
		});

		list.addMouseListener(this);
		updateTemplates();
		buildPopup();

	}
	
	public void unselect()  {
		list.clearSelection();
	}

	public void updateTemplates() {
		model.removeAllElements();
		for (String t : TemplateManager.getInstance().getTemplateList()) {
			if (t != null && t.trim().length() > 0) {
				model.addElement(t);
			}
		}

		this.updateUI();
	}

	@Override
	public void mouseClicked(MouseEvent e) {
		if (SwingUtilities.isRightMouseButton(e)) {
			if(list.getSelectedIndex()>=0) {
				popup.show(this, e.getX(), e.getY());
			}

		}
	}

	private void buildPopup() {
		popup = new JPopupMenu();
		ActionListener aListener = new ActionListener() {
			@Override
			public void actionPerformed(ActionEvent ae) {
				if (ae.getActionCommand().equals("Delete")) {
					TemplateManager.getInstance().deleteTemplate(list.getSelectedValue());
				    updateTemplates();
				}
			}

		};
		JMenuItem item;
		popup.add(item = new JMenuItem("Delete"));
		item.addActionListener(aListener);
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
}
