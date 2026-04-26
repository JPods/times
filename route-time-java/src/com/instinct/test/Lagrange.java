package com.instinct.test;
import java.awt.geom.Point2D;
import java.util.ArrayList;
import java.util.List;

public class Lagrange  {
	Point2D[] puntos;	// Points
	int pcurso=N;	// index of current point
	// Constantes
	static final int N = 4; // Number of points
	static final int R = 8; // Radius of the points

	public void init(Point2D points[]) {
		puntos = points;
	}

	// Compute the value of j-th Lagrange polynomial
	private double lagr(int i, double t){
		double pr=1.0;
		for(int j=0; j < N; ++j) 
			if(j != i) pr*=(t*(N-1.0)-j)/(i-j);
		return pr;
	}

	public List<Point2D> computeLines() {
		List<Point2D> points=new ArrayList<Point2D>();
		// Draw the segment (px,py), (qx,qy)
		double qx=puntos[0].getX(), qy=puntos[0].getY(), px, py;


		// Fill with white
		for(double t=0.0; t<=1.0; t+=0.01){
			// nuevo-> antiguo
			px=qx; py=qy; qx=0.0; qy=0.0;
			// Calcula nuevo
			for(int i=0; i<N; ++i){
				qx+=(double)(puntos[i].getX())*lagr(i,t);
				qy+=(double)(puntos[i].getY())*lagr(i,t);
			}
			points.add(new Point2D.Double((px-.00005),(py-.00005)));
		}
		points.add(new Point2D.Double(puntos[N-1].getX(),puntos[N-1].getY()));
		return points;
	}

}