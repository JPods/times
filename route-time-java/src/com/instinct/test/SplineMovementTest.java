package com.instinct.test;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.Shape;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.geom.Path2D;
import java.awt.geom.PathIterator;
import java.awt.geom.Point2D;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JFrame;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;


public class SplineMovementTest
{
    public static void main(String[] args)
    {
        SwingUtilities.invokeLater(new Runnable()
        {
            @Override
            public void run()
            {
                createAndShowGUI();
            }
        });
    }

    private static PathFollower pathFollower;

    private static void createAndShowGUI()
    {
        JFrame frame = new JFrame();
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.getContentPane().setLayout(new BorderLayout());

        final Random random = new Random(0);

        final SplineMovementPanel p = new SplineMovementPanel();

        JButton generateButton = new JButton("Generate");
        generateButton.addActionListener(new ActionListener()
        {
            @Override
            public void actionPerformed(ActionEvent e)
            {
                Shape spline = generateSpline(p,
                    random.nextDouble(),  
                    random.nextDouble(),  
                    random.nextDouble());
                p.setSpline(spline);
                pathFollower = new PathFollower(spline);
                p.repaint();
            }
        });
        frame.getContentPane().add(generateButton, BorderLayout.NORTH);
        startAnimation(p);

        frame.getContentPane().add(p, BorderLayout.CENTER);
        frame.setSize(800, 800);
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    private static Shape generateSpline(
        JComponent c, double yLeft, double yCenter, double yRight)
    {
        Path2D spline = new Path2D.Double();
        double x0 = 0;
        double y0 = yLeft * c.getHeight();
        double x1 = c.getWidth() / 2;
        double y1 = yCenter * c.getHeight();
        double x2 = c.getWidth();
        double y2 = yRight * c.getHeight();
        spline.moveTo(x0, y0);
        spline.curveTo(x1, y1, x1, y1, x2, y2);
        return spline;
    }

    private static void startAnimation(final SplineMovementPanel p)
    {
        Timer timer = new Timer(20, new ActionListener()
        {
            double position = 0.0;

            @Override
            public void actionPerformed(ActionEvent e)
            {
                position += 0.005;
                position %= 1.0;
                if (pathFollower != null)
                {
                    Point2D point = pathFollower.computePointAt(position * pathFollower.getPathLength());
                    p.setObjectLocation(point);
                }
            }
        });
        timer.start();
    }
}

class PathFollower
{
    private final List<Point2D> points;
    private final double pathLength;
    private Point2D controlPt;
    PathFollower(Shape spline)
    {
        points = createPointList(spline);
        pathLength = computeLength(points);
    }

    public double getPathLength()
    {
        return pathLength;
    }

    Point2D computePointAt(double length)
    {
        if (length < 0)
        {
            Point2D p = points.get(0);
            return new Point2D.Double(p.getX(), p.getY());
        }
        if (length > pathLength)
        {
            Point2D p = points.get(points.size()-1);
            return new Point2D.Double(p.getX(), p.getY());
        }
        double currentLength = 0;
        for (int i=0; i<points.size()-1; i++)
        {
            Point2D p0 = points.get(i);
            Point2D p1 = points.get(i+1);
            double distance = p0.distance(p1);
            double nextLength = currentLength + distance;
            if (nextLength > length)
            {
                double rel = 1 - (nextLength - length) / distance;
                double x0 = p0.getX();
                double y0 = p0.getY();
                double dx = p1.getX() - p0.getX();
                double dy = p1.getY() - p0.getY();
                double x = x0 + rel * dx;
                double y = y0 + rel * dy;
                return new Point2D.Double(x,y);
            }
            currentLength = nextLength;
        }
        Point2D p = points.get(points.size()-1);
        return new Point2D.Double(p.getX(), p.getY());
    }

    private static double computeLength(List<Point2D> points)
    {
        double length = 0;
        for (int i=0; i<points.size()-1; i++)
        {
            Point2D p0 = points.get(i);
            Point2D p1 = points.get(i+1);
            length += p0.distance(p1);
        }
        return length;
    }

    private static List<Point2D> createPointList(Shape shape)
    {
        List<Point2D> points = new ArrayList<Point2D>();
        PathIterator pi = shape.getPathIterator(null,  0.1);
        double coords[] = new double[6];
        while (!pi.isDone())
        {
            int s = pi.currentSegment(coords);
            switch (s)
            {
                case PathIterator.SEG_MOVETO:
                    points.add(new Point2D.Double(coords[0], coords[1]));

                case PathIterator.SEG_LINETO:
                    points.add(new Point2D.Double(coords[0], coords[1]));
            }
            pi.next();
        }
        return points;
    }

}


class SplineMovementPanel extends JPanel
{
    void setSpline(Shape shape)
    {
        this.spline = shape;
    }

    void setObjectLocation(Point2D objectLocation)
    {
        this.objectLocation = objectLocation;
        repaint();
    }
    private Shape spline = null;
    private Point2D objectLocation = null;


    @Override
    protected void paintComponent(Graphics gr)
    {
        super.paintComponent(gr);
        Graphics2D g = (Graphics2D)gr;
        g.setRenderingHint(
            RenderingHints.KEY_ANTIALIASING, 
            RenderingHints.VALUE_ANTIALIAS_ON);

        if (spline != null)
        {
            g.setColor(Color.BLACK);
            g.draw(spline);
        }

        if (objectLocation != null)
        {
            g.setColor(Color.RED);
            int x = (int)objectLocation.getX()-15;
            int y = (int)objectLocation.getY()-15;
            g.fillOval(x, y, 30, 30);
        }
    }


}