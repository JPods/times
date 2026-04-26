package com.instinct.gui.pad.widgets;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.Shape;
import java.awt.Stroke;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Point2D;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.PodPainter;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Node;
import com.instinct.objects.pod.Pod;

public class PodUI {
	private Pod pod;

	private final static int LENGTH = 3;


	public PodUI(Pod pod) {
		this.pod = pod;
	}

	public void draw(Pad pad, Graphics2D g2) {
		Point2D p = getPoint(pad);
		if (p == null) {
			return;
		}
		Shape shape = getShape(g2, p);
		if (pod.isCrashed()) {
			crashGlow(g2, p, shape);
		} else if (pod.isGlow()) {
			glow(g2, p, shape);
		} else if (pod.isMergeLockOn()) {
			mergeLockGlow(g2, p, shape);
		}
		putLabel(g2, p);
	}

	private Shape getShape(Graphics2D g2, Point2D p) {

		double meterPerPixel = Pad.getInstance().getMeterPerPixel();
		Color c = PodPainter.getInstance().getColor(pod);
		g2.setColor(c);
		Shape shape = null;
		if (meterPerPixel > 1) {
			shape = new Ellipse2D.Double(p.getX() - 2, p.getY() - 2, 4, 4);
		} else {
			double h = LENGTH / meterPerPixel;
			shape = new Ellipse2D.Double(p.getX() - h/2, p.getY() - h/2, h, h);
		}
		
		g2.draw(shape);
		g2.fill(shape);
		return shape;
	}
	
	private Point2D rotate(int degree, Point2D origin, Point2D p1) {
		double radian = Math.toRadians(degree);
		double newX = origin.getX() + ( Math.cos(radian) * (p1.getX()-origin.getX()) + Math.sin(radian) * (p1.getY() -origin.getY()));
		double newY = origin.getY() + (-Math.sin(radian) * (p1.getX()-origin.getX()) +Math.cos(radian) * (p1.getY() -origin.getY()));
		return new Point2D.Double(newX, newY);
	
	}
	


	private void glow(Graphics2D g2, Point2D p, Shape shape) {
		Stroke stroke = new BasicStroke(4.0f);
		Stroke old = g2.getStroke();
		g2.setStroke(stroke);
		g2.setColor(Color.YELLOW);
		Rectangle r = shape.getBounds();
		int x = (int) r.getX();
		int y = (int) r.getY();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

		g2.setColor(Color.BLACK);
		g2.drawString(pod.getId(), x - width, y - height);
		g2.setStroke(old);
	}

	private void crashGlow(Graphics2D g2, Point2D p, Shape shape) {
		Stroke stroke = new BasicStroke(4.0f);
		Stroke old = g2.getStroke();
		g2.setStroke(stroke);
		g2.setColor(Color.RED);
		Rectangle r = shape.getBounds();
		int x = (int) r.getX();
		int y = (int) r.getY();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

		g2.setStroke(old);
	}

	private void mergeLockGlow(Graphics2D g2, Point2D p, Shape shape) {
		Stroke stroke = new BasicStroke(2.0f);
		Stroke old = g2.getStroke();
		g2.setStroke(stroke);
		g2.setColor(Color.BLUE);
		Rectangle r = shape.getBounds();
		int x = (int) r.getX();
		int y = (int) r.getY();
		int width = (int) r.getWidth();
		int height = (int) r.getHeight();

		g2.drawLine(x, y, x + width, y);
		g2.drawLine(x + width, y, x + width, y + height);
		g2.drawLine(x + width, y + height, x, y + height);
		g2.drawLine(x, y + height, x, y);

		g2.setStroke(old);
	}

	private void putLabel(Graphics2D g2, Point2D p) {
		if (Pad.getInstance().getZoom() < 18) {
			return;
		}
		String text = pod.getId();
		if (!pod.isParked()) {
			Node dest = pod.getDestinationNode();
			text = text + " (" + dest.getId() + ")";
		}
		g2.setColor(Color.BLACK);
		g2.setFont(new Font("default", Font.PLAIN, 11));
		g2.drawString(pod.getId(), (int) p.getX(), (int) p.getY() - 20);
	}

	private Point2D getPoint(Pad pad) {
		if (pod.getDistanceSinceLastNode() < 1) {
			return GUIUtil.getMapPoint(pad, pod.getLastNode());
		} else {
			if (pod.getCurrentLine() == null) {
				return null;
			} else {
				return pod.getCurrentLine().getPointAt(pad, pod.getDistanceSinceLastNode());
			}
		}
	}

}
