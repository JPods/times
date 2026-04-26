package com.instinct.gui;

import java.awt.Color;
import java.awt.Paint;

import org.jfree.chart.renderer.category.BarRenderer;

import com.instinct.objects.simulation.SimulationSettings;
import com.instinct.service.WorkspaceManager;

public class CustomRenderer extends BarRenderer {
	SimulationSettings ss=WorkspaceManager.getInstance().getWorkingSim().getSettings();
	private Color colors[]= new Color[] {Color.decode(ss.getTrainBarColor()), Color.decode(ss.getBusBarColor()), Color.decode(ss.getCarBarColor()), Color.decode(ss.getJpodBarColor())};
	
	public Paint getItemPaint(final int row, final int column) 
	 { 
		
	    return colors[column]; 
	 } 
}