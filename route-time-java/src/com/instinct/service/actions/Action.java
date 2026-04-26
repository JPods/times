package com.instinct.service.actions;

import java.awt.Point;

import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Network;

public interface Action<T> {

	public T execute(Point p);
	
	public void undo();
	
	public boolean validate(Pad pad, Network net, Point p);
	
	public boolean isDone();

	public void init(Point p);
	
	public void abort();

}
