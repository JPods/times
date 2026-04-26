package com.instinct.service.actions;


public class ActionFactoryBuilder {
	
	private static ActionFactoryBuilder instance=new ActionFactoryBuilder();
	
	public static ActionFactoryBuilder getInstance() {
		return instance;
	}
	
	public ActionFactory getLineAddFac() {
		return new LineAddActionFactory();
	}
	
	
	public ActionFactory getSwitchAddFac() {
		return new SwitchAddActionFactory();
	}
	
	public ActionFactory getTemplateAddFac(String template) {
		return new TemplateAddActionFactory(template);
	}
	
	
	public ActionFactory getCircleAddFac() {
		return new CircleAddActionFactory();
	}
	
	public ActionFactory getStationMarkFac() {
		return new MarkStationActionFactory();
	}

	public ActionFactory getDoubleLineFac() {
		return new DoubleLineAddActionFactory();
	}

	public ActionFactory getFenceAddFac() {
		return new FenceAddActionFactory();
	}

}


class DoubleLineAddActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new DoubleLineAddAction();
	}
}

class LineAddActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new LineAddAction();
	}
}

class FenceAddActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new FenceAddAction();
	}
}


class TemplateAddActionFactory implements ActionFactory {
	
	private String t;
	
	public TemplateAddActionFactory(String t)  {
		this.t=t;
	}
	
	@Override
	public Action createAction() {
		return new TemplateAddAction(t);
	}
}

class SwitchAddActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new SwitchAddAction();
	}

}


class CircleAddActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new CircleAddAction();
	}

}


class MarkStationActionFactory implements ActionFactory {
	@Override
	public Action createAction() {
		return new MarkStationAction();
	}

}

