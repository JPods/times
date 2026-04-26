package com.instinct.gui;

import java.awt.Color;
import java.awt.Image;
import java.awt.geom.Line2D;
import java.awt.geom.Point2D;
import java.awt.geom.Rectangle2D;
import java.io.File;
import java.net.MalformedURLException;
import java.net.URL;
import java.text.DecimalFormat;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import javax.swing.ImageIcon;
import javax.swing.JDialog;
import javax.swing.JTree;

import org.openstreetmap.gui.jmapviewer.Coordinate;

import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.NodeGroup;
import com.instinct.objects.network.Station;
import com.instinct.objects.network.Switch;

public class GUIUtil {

	private static int r = 0, g = 0;
	private static Color c = Color.BLACK;
	
    private static DecimalFormat df6 = new DecimalFormat("000000");
    private static DecimalFormat df4 = new DecimalFormat("0000");
    private static DecimalFormat df22 = new DecimalFormat("00.00");
    private static DecimalFormat df42 = new DecimalFormat("0000.00");
	private static JDialog dlg;
	
	public static ImageIcon getImage(String file) {
		return getImageWithScale(file, 24, 24);
	}
	
	public static ImageIcon getImageNoScale(String file) {
		URL url=GUIUtil.class.getResource("/images/"+file);
		if(url==null)  {
			File f=new File("./images/"+file);
			try {
				url=f.toURI().toURL();
			} catch (MalformedURLException e) {
				e.printStackTrace();
			}
		}
		ImageIcon icon=new ImageIcon(url);
		return icon;
	}
	
	public static ImageIcon getImageWithScale(String file, int width, int height) {
		ImageIcon icon=getImageNoScale(file);
		Image scaled=icon.getImage().getScaledInstance(width, height, Image.SCALE_SMOOTH);
		icon.setImage(scaled);
		return icon;
	}
	
	public static ImageIcon getLogoImage(String file) {
		return getImageWithScale(file, 175, 64);
	}

	
	public static String format42(double d) {
		return df42.format(d);
	}
	
	public static String format6(double d) {
		return df6.format(d);
	}
	
	
	public static String format4(double d) {
		return df4.format(d);
	}
	
	
	public static String format22(double d) {
		return df22.format(d);
	}
	
	
	
	public static Point2D getMapPoint(Pad pad, Node node) {
		if (node == null) {
			return null;
		}
		return pad.getMapPosition(node.getLat(), node.getLon(),false);
	}

	public static Point2D getMapPoint(Pad pad, Coordinate node) {
		if (node == null) {
			return null;
		}
		return pad.getMapPosition(node.getLat(), node.getLon(),false);
	}
	
	public static void expandAll(JTree jTree) {
		for (int i = 0; i < jTree.getRowCount(); i++) {
			jTree.expandRow(i);
		}
	}

	public Point2D[] getIntersectionPoint(Line2D line, Rectangle2D rectangle) {

        Point2D[] p = new Point2D[4];

        // Top line
        p[0] = getIntersectionPoint(line,
                        new Line2D.Double(
                        rectangle.getX(),
                        rectangle.getY(),
                        rectangle.getX() + rectangle.getWidth(),
                        rectangle.getY()));
        // Bottom line
        p[1] = getIntersectionPoint(line,
                        new Line2D.Double(
                        rectangle.getX(),
                        rectangle.getY() + rectangle.getHeight(),
                        rectangle.getX() + rectangle.getWidth(),
                        rectangle.getY() + rectangle.getHeight()));
        // Left side...
        p[2] = getIntersectionPoint(line,
                        new Line2D.Double(
                        rectangle.getX(),
                        rectangle.getY(),
                        rectangle.getX(),
                        rectangle.getY() + rectangle.getHeight()));
        // Right side
        p[3] = getIntersectionPoint(line,
                        new Line2D.Double(
                        rectangle.getX() + rectangle.getWidth(),
                        rectangle.getY(),
                        rectangle.getX() + rectangle.getWidth(),
                        rectangle.getY() + rectangle.getHeight()));

        return p;

    }

    public Point2D getIntersectionPoint(Line2D lineA, Line2D lineB) {

        double x1 = lineA.getX1();
        double y1 = lineA.getY1();
        double x2 = lineA.getX2();
        double y2 = lineA.getY2();

        double x3 = lineB.getX1();
        double y3 = lineB.getY1();
        double x4 = lineB.getX2();
        double y4 = lineB.getY2();

        Point2D p = null;

        double d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
        if (d != 0) {
            double xi = ((x3 - x4) * (x1 * y2 - y1 * x2) - (x1 - x2) * (x3 * y4 - y3 * x4)) / d;
            double yi = ((y3 - y4) * (x1 * y2 - y1 * x2) - (y1 - y2) * (x3 * y4 - y3 * x4)) / d;

            p = new Point2D.Double(xi, yi);

        }
        return p;
    }
    
    public static List<Node> sortStations(Collection<Station> collection)  {
    	String replacer="ST";
    	Map<Integer, Node> sortedMap=new TreeMap<Integer, Node>();
    	for(Node n:collection) {
    		Integer id=Integer.parseInt(n.getId().replace(replacer,""));
    		sortedMap.put(id, n);
    	}
    	
    	List<Node> result=new ArrayList<Node>();
    	
    	for(Integer id:sortedMap.keySet()) {
    		result.add(sortedMap.get(id));
    	}
    	return result;
    }
    
 

	public static List sortSwitches(Collection<Switch> collection) {
    	String replacer="SW";
    	Map<Integer, Node> sortedMap=new TreeMap<Integer, Node>();
    	for(Node n:collection) {
    		Integer id=Integer.parseInt(n.getId().replace(replacer,""));
    		sortedMap.put(id, n);
    	}
    	
    	List<Node> result=new ArrayList<Node>();
    	
    	for(Integer id:sortedMap.keySet()) {
    		result.add(sortedMap.get(id));
    	}
    	return result;
    }

	public static List sortLines(Collection<Line> collection) {
    	String replacer="L";
    	Map<Integer, Line> sortedMap=new TreeMap<Integer, Line>();
    	for(Line n:collection) {
    		Integer id=Integer.parseInt(n.getId().replace(replacer,""));
    		sortedMap.put(id, n);
    	}
    	
    	List<Line> result=new ArrayList<Line>();
    	
    	for(Integer id:sortedMap.keySet()) {
    		result.add(sortedMap.get(id));
    	}
    	return result;	
    }

	public static List sortNodeGroups(Collection<NodeGroup> collection) {
		String replacer="NG-";
    	Map<Integer, NodeGroup> sortedMap=new TreeMap<Integer, NodeGroup>();
    	for(NodeGroup n:collection) {
    		Integer id=Integer.parseInt(n.getId().replace(replacer,""));
    		sortedMap.put(id, n);
    	}
    	
    	List<NodeGroup> result=new ArrayList<NodeGroup>();
    	
    	for(Integer id:sortedMap.keySet()) {
    		result.add(sortedMap.get(id));
    	}
    	return result;	
	}
	

}


