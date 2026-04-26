package com.instinct.gui.pad.widgets;

import java.awt.Graphics2D;
import java.awt.Point;

import com.instinct.gui.pad.Pad;

public interface Drawable<T> {

	void setHighlight(boolean isHighLight);
	void setGlow(boolean isGlow);
	boolean contains(Point p);
	void draw(Graphics2D g2, Pad pad);
	String getId();
	void showEditor();
	T getModel();
	
	public double distance(Point p);
	
	public void setGrouped(boolean isGrouped);

}
