package com.instinct.gui.guactions;

import java.awt.event.ActionEvent;
import java.util.ArrayList;
import java.util.List;

import javax.swing.AbstractAction;
import javax.swing.Action;
import javax.swing.JComponent;
import javax.swing.KeyStroke;

import com.instinct.gui.MainFrame;

public class KeyBinder {

	private static KeyBinder instance=new KeyBinder();
	
	private List<Holder> holders=new ArrayList<Holder>();
	
	
	public static KeyBinder getInstance() {
		return instance;
	}
	
	public void bind(int ke, final Action action, String key) {
	    KeyStroke keyS = KeyStroke.getKeyStroke(ke, 0, false);
	    Action keySAction = new AbstractAction()
	    {
	      public void actionPerformed(ActionEvent e)
	      {
	    	  action.actionPerformed(e);
	      }
	    };
	    
	    Holder h=new Holder(keyS, keySAction, key);
	    holders.add(h);

	}
	
	public void bindWithMainFrame() {
		for(Holder h:holders)  {
		    MainFrame.getInstance().getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(h.getKs(), h.getKey());
		    MainFrame.getInstance().getRootPane().getActionMap().put(h.getKey(),h.getAction());
		}
	}
	
	
	private KeyBinder() {
	}
}

class Holder {
	private KeyStroke ks;
	private Action action;
	private String key;
	public KeyStroke getKs() {
		return ks;
	}
	public Action getAction() {
		return action;
	}
	public String getKey() {
		return key;
	}
	public Holder(KeyStroke ks, Action action, String key) {
		this.ks = ks;
		this.action = action;
		this.key = key;
	}
	
	
}
