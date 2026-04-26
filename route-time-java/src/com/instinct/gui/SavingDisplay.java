package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Dimension;

import javax.swing.BoxLayout;
import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.border.Border;
import javax.swing.border.EmptyBorder;

import org.jfree.chart.ChartFactory;
import org.jfree.chart.ChartPanel;
import org.jfree.chart.JFreeChart;
import org.jfree.chart.axis.CategoryAxis;
import org.jfree.chart.axis.CategoryLabelPositions;
import org.jfree.chart.axis.NumberAxis;
import org.jfree.chart.plot.CategoryPlot;
import org.jfree.chart.plot.PlotOrientation;
import org.jfree.chart.renderer.category.BarRenderer;
import org.jfree.data.category.CategoryDataset;
import org.jfree.data.category.DefaultCategoryDataset;

import com.instinct.service.WorkspaceManager;

public class SavingDisplay extends JDialog {

	private final int whPerKmPod = 79;
	private final int whPerKmCar = 642;
	private final int whPerKmBus = 774;
	private final int whPerKmRail = 547;

	private final double landPerKmPod = 0.5 * 3000;
	private final double landPerKmCar = 10 * 3000;
	private final double landPerKmBus = 8 * 3000;
	private final double landPerKmRail = 14 * 3000;

	private final int speedCar = 38;
	private final int speedBus = 15;
	private final int speedRail = 29;

	private double km;
	private double length;
	private double avgSpeed;

	private final String rail = "Rail";
	private final String bus = "Bus";
	private final String car = "Car";
	private final String jpod = "JPod";

	public SavingDisplay() {
		JPanel container = new JPanel();
		container.setLayout(new BoxLayout(container, BoxLayout.X_AXIS));
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		km = WorkspaceManager.getInstance().getWorkingSim().getSummary().getTotalTripDistanceInKM();
		avgSpeed = WorkspaceManager.getInstance().getWorkingSim().getSummary().getAvgVelocityInKMPH();
		length = WorkspaceManager.getInstance().getNetwork().getTotalLineLength() / 1000;
		this.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
		setTitle("Savings");
		final CategoryDataset dataset2 = createDataset2();
		final JFreeChart chart2 = createChart("Hours", dataset2);
		final ChartPanel chartPanel2 = new ChartPanel(chart2);
		chartPanel2.setPreferredSize(new Dimension(300, 450));
		container.add(chartPanel2);

		final CategoryDataset dataset1 = createDataset1();
		final JFreeChart chart1 = createChart("KWh", dataset1);
		final ChartPanel chartPanel1 = new ChartPanel(chart1);
		chartPanel1.setPreferredSize(new Dimension(300, 450));
		container.add(chartPanel1);

		final CategoryDataset dataset3 = createDataset3();
		final JFreeChart chart3 = createChart("Sqr. Feet (1000s)", dataset3);
		final ChartPanel chartPanel3 = new ChartPanel(chart3);
		chartPanel3.setPreferredSize(new Dimension(300, 450));
		container.add(chartPanel3);

		this.setLayout(new BorderLayout());
		this.add(BorderLayout.CENTER, container);
		JLabel txt = new JLabel("<html>Survival:  Life requires energy. Oil is finite. Life powered by oil is terminal. Illicit Energy, "
				+ "dependence on energy outside self-reliance from oil, has <br>resulted in oil-wars since 1990 and will result in "
				+ "Oil Famine as oil resources deplete or political instability collapses access to Illicit Energy.</html>");
		Border margin = new EmptyBorder(20, 20, 20, 20);
		txt.setBorder(margin);
		this.add(BorderLayout.SOUTH, txt);
		pack();
		setLocationRelativeTo(null);
	}

	/**
	 * Creates a sample chart.
	 * 
	 * @param dataset
	 *            the dataset.
	 * 
	 * @return The chart.
	 */
	private JFreeChart createChart(String unit, final CategoryDataset dataset) {

		// create the chart...
		final JFreeChart chart = ChartFactory.createBarChart("", // chart title
				"", // domain axis label
				unit, // range axis label
				dataset, // data
				PlotOrientation.VERTICAL, // orientation
				true, // include legend
				true, // tooltips?
				false // URLs?
				);

		// get a reference to the plot for further customisation...
		final CategoryPlot plot = chart.getCategoryPlot();

		// set the range axis to display integers only...
		final NumberAxis rangeAxis = (NumberAxis) plot.getRangeAxis();
		rangeAxis.setStandardTickUnits(NumberAxis.createIntegerTickUnits());

		plot.setRenderer(new CustomRenderer());
		// disable bar outlines...
		final BarRenderer renderer = (BarRenderer) plot.getRenderer();
		renderer.setMaximumBarWidth(.05);

		final CategoryAxis domainAxis = plot.getDomainAxis();
		domainAxis.setCategoryLabelPositions(CategoryLabelPositions.createUpRotationLabelPositions(Math.PI / 6.0));
		// OPTIONAL CUSTOMISATION COMPLETED.

		return chart;
	}

	private CategoryDataset createDataset1() {

		// row keys...
		final String energy = "Energy/Pollution";

		// create the dataset...
		final DefaultCategoryDataset dataset = new DefaultCategoryDataset();

		dataset.addValue(km * whPerKmRail / 1000, energy, rail);
		dataset.addValue(km * whPerKmBus / 1000, energy, bus);
		dataset.addValue(km * whPerKmCar / 1000, energy, car);
		dataset.addValue(km * whPerKmPod / 1000, energy, jpod);

		return dataset;

	}

	private CategoryDataset createDataset2() {

		// row keys...
		final String time = "Trip Time";

		// create the dataset...
		final DefaultCategoryDataset dataset = new DefaultCategoryDataset();

		dataset.addValue(km / speedRail, time, rail);
		dataset.addValue(km / speedBus, time, bus);
		dataset.addValue(km / speedCar, time, car);
		dataset.addValue(km / avgSpeed, time, jpod);

		return dataset;

	}

	private CategoryDataset createDataset3() {

		// row keys...
		final String land = "Land Use Without Parking";

		// create the dataset...
		final DefaultCategoryDataset dataset = new DefaultCategoryDataset();

		dataset.addValue(landPerKmRail * length / 1000, land, rail);
		dataset.addValue(landPerKmBus * length / 1000, land, bus);
		dataset.addValue(landPerKmCar * length / 1000, land, car);
		dataset.addValue(landPerKmPod * length / 1000, land, jpod);

		return dataset;

	}
}

