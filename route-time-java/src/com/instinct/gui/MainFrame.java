package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Container;
import java.awt.Frame;
import java.awt.KeyboardFocusManager;
import java.io.File;

import javax.swing.JFrame;
import javax.swing.JSplitPane;

import com.instinct.gui.guactions.KeyBinder;
import com.instinct.gui.pad.KeyController;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.gui.tree.NetworkTree;
import com.instinct.gui.tree.NodeGroupsPanel;
import com.instinct.gui.tree.TemplatesPanel;
import com.instinct.service.WorkspaceManager;

public class MainFrame extends JFrame{
	
	private JSplitPane leftRightSplit, rootTopDownSplit, lowerTopDownSplit;
	
	private static MainFrame instance;
	
	public static MainFrame getInstance() {
		return instance;
	}
	private MainFrame()  {
		   this.setIconImage(GUIUtil.getImage("icon.png").getImage());	
		   Container contentPane = getContentPane();
		    contentPane.setBackground(new Color(0xFF, 0xCC, 0xCC));
		    this.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		    
		    Toolbar palette=Toolbar.getInstance();

		    contentPane.setLayout(new BorderLayout());
		    contentPane.add(palette, BorderLayout.NORTH);
		    this.setExtendedState(Frame.MAXIMIZED_BOTH);
		    Pad pad=Pad.getInstance();
		    
		    lowerTopDownSplit=new JSplitPane(JSplitPane.VERTICAL_SPLIT,NetworkTree.getInstance(), NodeGroupsPanel.getInstance());
		    lowerTopDownSplit.setDividerLocation(500);
		    lowerTopDownSplit.setOneTouchExpandable(true);
		    
		    rootTopDownSplit=new JSplitPane(JSplitPane.VERTICAL_SPLIT,TemplatesPanel.getInstance(), lowerTopDownSplit);
		    rootTopDownSplit.setOneTouchExpandable(true);
		    rootTopDownSplit.setDividerLocation(200);
		    leftRightSplit=new JSplitPane(JSplitPane.HORIZONTAL_SPLIT,rootTopDownSplit, pad);
		    leftRightSplit.setOneTouchExpandable(true);
		    leftRightSplit.setDividerLocation(300);
		    contentPane.add(leftRightSplit, BorderLayout.CENTER);
		    contentPane.add(StatusBar.getInstance(), BorderLayout.SOUTH);
		    KeyboardFocusManager.getCurrentKeyboardFocusManager().addKeyEventDispatcher(new KeyController());
		    this.setTitle("Route-Time");
		    this.pack();
		    contentPane.validate();
		    this.setLocationByPlatform(true);
		    
		
	}
	
	
	public static void main(String args[]) {
		instance=new MainFrame();
		instance.setVisible(true);
		KeyBinder.getInstance().bindWithMainFrame();
		KeyboardFocusManager.getCurrentKeyboardFocusManager().addKeyEventDispatcher(SelectionManager.getInstance());
		if(args.length==1 && args[0].endsWith(".jpd"))  {
			WorkspaceManager.getInstance().openFile(new File(args[0]));
		}
	}
}
