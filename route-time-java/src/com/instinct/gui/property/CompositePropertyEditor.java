package com.instinct.gui.property;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Toolkit;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.HashMap;
import java.util.Map;

import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTabbedPane;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;

public class CompositePropertyEditor extends JDialog {

	private EditAction action;
	private String btnLbl;
	private boolean isActionClicked = false;
	private JLabel headerLbl = new JLabel();
	private Map<String, Map<String,AttributeEditor<?>>> editors;
	private boolean isTabForm=false;

	public CompositePropertyEditor(String title, String btnLabel, Map<String, Map<String,AttributeEditor<?>>> editors, EditAction t) {
		this.editors = editors;
		setHeader(null, title, btnLabel, t);
		this.setLayout(new BorderLayout());
		this.add(headerLbl, BorderLayout.NORTH);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		createTabPanel();
		isTabForm=true;
		buildButtonPanel();
		this.pack();
		doCentering();
	}
	
	public CompositePropertyEditor(String optionalHeader, String title, String btnLabel, Map<String,AttributeEditor<?>> editorsList, EditAction t) {
		this.editors=new HashMap<String, Map<String,AttributeEditor<?>>>();
		editors.put("DUMMY", editorsList);
		setHeader(optionalHeader, title, btnLabel, t);
		this.setLayout(new BorderLayout());
		this.add(headerLbl, BorderLayout.NORTH);
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		createSimplePanel();
		isTabForm=false;
		buildButtonPanel();
		this.pack();
		doCentering();
	}
	
	private void doCentering() {
		final Toolkit toolkit = Toolkit.getDefaultToolkit();
		final Dimension screenSize = toolkit.getScreenSize();
		final int x = (screenSize.width - this.getWidth()) / 2;
		final int y = (screenSize.height - this.getHeight()) / 2;
		this.setLocation(x, y);
	}

	private void createSimplePanel() {
		PropertyEditorComponent c = new PropertyEditorComponent(editors.get("DUMMY"));
		this.add(c, BorderLayout.CENTER);
	}

	private void setHeader(String optionalHeader, String title, String btnLabel, EditAction t) {
		this.btnLbl = btnLabel;
		this.setTitle(title);
		headerLbl.setHorizontalAlignment(JLabel.CENTER);
		this.action = t;
		if (optionalHeader != null) {
			headerLbl.setText(optionalHeader);
		}
		this.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
	}


	private void buildButtonPanel() {
		JPanel bottonPanel = new JPanel();
		bottonPanel.setLayout(new BoxLayout(bottonPanel, BoxLayout.X_AXIS));
		bottonPanel.setBackground(Color.GRAY);
		bottonPanel.add(Box.createVerticalStrut(45));
		JButton saveBtn = new JButton(btnLbl);
		saveBtn.addActionListener(new ActionListener() {
			public void actionPerformed(ActionEvent arg0) {
				save();
			}
		});
		JButton cancelBtn = new JButton("Cancel");
		cancelBtn.addActionListener(new ActionListener() {

			@Override
			public void actionPerformed(ActionEvent e) {
				dispose();

			}
		});
		bottonPanel.add(Box.createHorizontalGlue());
		bottonPanel.add(saveBtn);
		bottonPanel.add(Box.createHorizontalStrut(10));
		bottonPanel.add(cancelBtn);
		bottonPanel.add(Box.createHorizontalStrut(10));
		this.add(BorderLayout.SOUTH, bottonPanel);
	}

	private void createTabPanel() {
		JTabbedPane panel = new JTabbedPane();
		this.add(panel, BorderLayout.CENTER);

		for (Map.Entry<String, Map<String,AttributeEditor<?>>> entry : editors.entrySet()) {
			PropertyEditorComponent c = new PropertyEditorComponent(entry.getValue());
			panel.addTab(entry.getKey(), c);
		}
	}

	public boolean isActionClicked() {
		return isActionClicked;
	}

	private void save() {
		isActionClicked = true;
		
		if (action != null) {
			if(isTabForm) {
				action.doEditMultiple(this.editors);
			} else {
				action.doEdit(this.editors.get("DUMMY"));
			}
		}
		this.setVisible(false);
	}
}
