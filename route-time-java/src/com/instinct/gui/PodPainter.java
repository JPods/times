package com.instinct.gui;

import java.awt.Color;

import com.instinct.objects.Passenger;
import com.instinct.objects.pod.Pod;
import com.instinct.service.WorkspaceManager;

public class PodPainter {

	private static PodPainter instance=new PodPainter();
	
	private PodPainter() {
		
	}
	
	public static PodPainter getInstance() {
		return instance;
	}
	
	public Color getColor(Pod pod) {
		Color c=null;

		Passenger ps=pod.getPassenger();
		if(ps!=null && ps.isCalled()) {
			c=Color.BLUE;
		} else if(ps!=null && ps.isEvicted()) {
			c=Color.BLUE;
		}else if(pod.isParked()) {
			c=Color.WHITE;
		}
		else {
		 	double p=pod.getVelocity()/WorkspaceManager.getInstance().getWorkingSim().getSettings().getMaxVelocityInTU();
		 	if(p>1.0) {
		 		p=1.0;
		 	}
			c=interpolate(p);
		}
		
		return c;
	}
	
	 public Color interpolate(double p) {

		 	Color start=Color.red;
		 	Color end=Color.green;
	        float[] startHSB = Color.RGBtoHSB(start.getRed(), start.getGreen(), start.getBlue(), null);
	        float[] endHSB = Color.RGBtoHSB(end.getRed(), end.getGreen(), end.getBlue(), null);

	        float brightness = (startHSB[2] + endHSB[2]) / 2;
	        float saturation = (startHSB[1] + endHSB[1]) / 2;

	        float hueMax = 0;
	        float hueMin = 0;
	        if (startHSB[0] > endHSB[0]) {
	            hueMax = startHSB[0];
	            hueMin = endHSB[0];
	        } else {
	            hueMin = startHSB[0];
	            hueMax = endHSB[0];
	        }

	        double hue = ((hueMax - hueMin) * p) + hueMin;

	        return Color.getHSBColor((float)hue, saturation, brightness);
	    }
}
