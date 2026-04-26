package com.instinct.service;

import java.awt.Point;
import java.util.Deque;
import java.util.LinkedList;

import com.instinct.gui.pad.Pad;
import com.instinct.service.actions.Action;
import com.instinct.service.actions.ActionFactory;

public class ActionManager {

	private static ActionManager instance = new ActionManager();

	private Deque<Action> dq = new LinkedList<Action>();
	private ActionFactory currentActionFactory = null;
	private Action lastAct;

	private ActionManager() {

	}

	public static ActionManager getInstance() {
		return instance;
	}

	public void undo() {
		if (dq.size() == 0) {
			return;
		}
		Action a = dq.pop();
		a.undo();
		Pad.getInstance().notifyComponents();
	}

	private Object execute(Action<?> a, Point p) {
		Object o = a.execute(p);
		lastAct = a;
		Pad.getInstance().notifyComponents();
		return o;
	}

	public boolean consume(Point p) {
		if (currentActionFactory == null) {
			return false;
		}
		return invokeAction(p);
	}

	private boolean invokeAction(Point p) {
		Action a = null;
		boolean isNew=false;
		if (lastAct != null && !lastAct.isDone()) {
			a = lastAct;
			isNew=false;
		} else {
			a = currentActionFactory.createAction();
			isNew=true;
			a.init(p);
		}
		
		lastAct = a;
		boolean isValid = a.validate(Pad.getInstance(), WorkspaceManager.getInstance().getNetwork(), p);
		if (isValid) {
			execute(a, p);
			if(isNew) {
				dq.push(a);
			}
			return true;
		} else {
			return false;
		}
	}

	public void setActionFactory(ActionFactory fac) {
		if (lastAct != null) {
			lastAct.abort();
			lastAct = null;
		}
		currentActionFactory = fac;

	}
	
	public boolean isMarkStationAction() {
		return currentActionFactory!=null && currentActionFactory.getClass().getSimpleName().equals("MarkStationActionFactory");
	}

	public boolean isFenceAddAction() {
		return currentActionFactory!=null && currentActionFactory.getClass().getSimpleName().equals("FenceAddActionFactory");
	}
	
	public boolean isLineAddAction() {
		return currentActionFactory!=null && currentActionFactory.getClass().getSimpleName().equals("LineAddActionFactory");
	}

}
