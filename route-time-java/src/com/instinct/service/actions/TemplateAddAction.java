package com.instinct.service.actions;

import java.awt.Point;

import org.jdom2.Document;
import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Network;
import com.instinct.service.TemplateManager;
import com.instinct.service.serialization.MergingService;

public class TemplateAddAction implements Action {

	private String name;
	MergingService merger=new MergingService();
	
	public TemplateAddAction(String t) {
		this.name=t;
	}

	@Override
	public Object execute(Point p) {
		Document d;
		try {
			d = TemplateManager.getInstance().getTemplateModel(name);
			Coordinate c=Pad.getInstance().getPosition(p);
			merger.merge(d, c.getLat(), c.getLon());
		} catch (Exception e) {
			e.printStackTrace();
		}

		return null;
	}

	@Override
	public void undo() {
		merger.unmerge();
		Pad.getInstance().notifyComponents();
	}

	@Override
	public boolean validate(Pad pad, Network net, Point p) {
		return true;
	}

	@Override
	public void init(Point p) {
	}

	@Override
	public boolean isDone() {
		return true;
	}

	@Override
	public void abort() {
	}

}
