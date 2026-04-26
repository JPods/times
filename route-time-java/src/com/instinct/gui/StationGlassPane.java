package com.instinct.gui;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Shape;
import java.awt.Stroke;
import java.awt.geom.Line2D;
import java.awt.geom.Point2D;
import java.awt.geom.Rectangle2D;
import java.awt.geom.RoundRectangle2D;

import javax.swing.JPanel;

import com.instinct.config.Config;
import com.instinct.objects.network.Station;
import com.instinct.objects.pod.Pod;

public class StationGlassPane extends JPanel {

	private int POD_WIDTH=30;
	private int PIXEL_PER_METER=20;
	private int POD_LEN=Config.getInstance().getPodLen()*PIXEL_PER_METER;
	
	private Station st=null;
	
	public void setStation(Station st) {
		this.st=st;
	}
	
	public void paint(Graphics g) {
		super.paint(g);
		Graphics2D g2 = (Graphics2D) g;
		g2.setStroke(new BasicStroke(2));
		g2.setColor(Color.BLACK);
		
		drawLine((Graphics2D) g);
		
		if(st==null) {
			return;
		}
		
		drawPlatform((Graphics2D) g);
		
		
		for(Pod p:st.getEntry().getPodQueue().getAll()) {
			double gap=st.getEntry().getLength()-p.getDistanceSinceLastNode();
			if(gap<40) {
				drawEntryPod(p,(Graphics2D) g);
			}
		}
		
		for(Pod p:st.getExit().getPodQueue().getAll()) {
			double gap=p.getDistanceSinceLastNode();
			if(gap<20) {
				drawExitPod(p,(Graphics2D) g);
			}
		}
	}
	
	
	private void drawExitPod(Pod p, Graphics2D g2) {
		double g=p.getDistanceSinceLastNode()-Config.getInstance().getPodLen();
		int x=400+(int) (g*PIXEL_PER_METER);
		int y=160-POD_WIDTH/2;
		drawPod(p,g2,x,y);
	}

	private void drawEntryPod(Pod p, Graphics2D g2) {
		double g=(st.getEntry().getLength()-p.getDistanceSinceLastNode())+Config.getInstance().getPodLen();
		int x=400-(int) (g*PIXEL_PER_METER);
		int y=160-POD_WIDTH/2;
		drawPod(p,g2, x, y);
		
	}

	private void drawPod(Pod pod, Graphics2D g2, int x, int y) {
		Shape shape=new RoundRectangle2D.Double(x, y, POD_LEN,POD_WIDTH,10,10);
		Color oldColor=g2.getColor();
		Stroke oldStroke=g2.getStroke();
		g2.setStroke(new BasicStroke(2));
		g2.setColor(Color.BLACK);
		g2.draw(shape);

		g2.setColor(PodPainter.getInstance().getColor(pod));
		g2.fill(shape);
		g2.setColor(oldColor);
		g2.setStroke(oldStroke);
		Point2D p=new Point2D.Double(shape.getBounds2D().getCenterX(),shape.getBounds2D().getCenterY());
		putLabel(pod, g2, p);
	}
	
	private void putLabel(Pod pod, Graphics2D g2, Point2D p) {
		String text=pod.getId();
        g2.setColor(Color.BLACK);
		g2.setFont(new Font("default", Font.PLAIN, 10));
		g2.drawString(text, (int) p.getX()-20, (int)p.getY());
	}
	

	private void drawPlatform(Graphics2D g2) {
		int berths=st.getPodQueue().getCapacity();
		int width=berths*(POD_LEN+Config.getInstance().getPodSpace()*PIXEL_PER_METER);
		int height=100;
		int gap=(POD_WIDTH/2)+8;
		int x=400-width;
		int y=160-height-gap;
		Color oldColor=g2.getColor();
		Stroke oldStroke=g2.getStroke();
		g2.setStroke(new BasicStroke(2));
		g2.setColor(Color.BLACK);
		Shape s=new Rectangle2D.Double(x, y, width,height);
		g2.draw(s);
		g2.setColor(Color.ORANGE);
		g2.fill(s);
		g2.setColor(oldColor);
		
		g2.setStroke(new BasicStroke(2));
		g2.setFont(new Font("default", Font.BOLD, 17));
		g2.drawString("Passengers Waiting:"+st.getPassengerQueue().size(), x+20, y+20);
		g2.setStroke(oldStroke);
		
		
	}

	private void drawLine(Graphics2D g2) {
		Stroke oldStroke=g2.getStroke();
		g2.setStroke(new BasicStroke(4));
		g2.draw(new Line2D.Double(0, 160, 600, 160));
		g2.setStroke(oldStroke);
	}
}
