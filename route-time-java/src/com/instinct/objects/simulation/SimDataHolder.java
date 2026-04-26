package com.instinct.objects.simulation;

import java.io.Serializable;
import java.text.DecimalFormat;
import java.util.ArrayList;
import java.util.List;

import com.instinct.objects.Passenger;
import com.instinct.objects.network.Line;
import com.instinct.objects.network.Network;
import com.instinct.objects.network.Node;
import com.instinct.objects.network.Station;
import com.instinct.service.RouteTableService;
import com.instinct.service.StaticUtil;
import com.instinct.service.WorkspaceManager;

public class SimDataHolder implements Serializable {

	private DecimalFormat df2 = new DecimalFormat("00");
	private String name;
	private long realTime;
	private SimulationSettings settings = new SimulationSettings();
	private long startTimeMs;

	private LoadArray load;
	private SummaryTripStats summary = new SummaryTripStats();
	private List<LineData> linesData = new ArrayList<LineData>();
	private List<StationData> stationsData = new ArrayList<StationData>();

	private int tick = 0;
	private TimeGridData times = null;

	private boolean isCompleted = false;

	public SimDataHolder() {
	}

	public void initialize() {
		Network net = WorkspaceManager.getInstance().getNetwork();

		stationsData.clear();
		for (Station st : net.getAllStations()) {
			st.initPodQueue();
			StationData sd = new StationData();
			sd.setData(st);
			stationsData.add(sd);
		}

		linesData.clear();
		for (Line line : net.getAllLines()) {
			LineData ld = new LineData();
			ld.setData(line);
			linesData.add(ld);
		}
		load = new LoadArray();
		LoadArrayLoader dlal = new DefaultLoadArrayLoader(net.getAllStations());
		load.init(net.getAllStations(), dlal);

		summary = new SummaryTripStats();
		times = new TimeGridData();

	}

	public void setTime(TimeGridData time) {
		this.times = time;
	}

	public void setLoad(LoadArray load) {
		this.load = load;
	}

	public void setLinesData(LineDataIntermediateForm[] linesData) {
		this.linesData = new ArrayList<LineData>();
		for (LineDataIntermediateForm li : linesData) {
			this.linesData.add(li.getLineData());
		}
	}

	public void setStationsData(StationDataIntermediateForm[] stationsData) {
		this.stationsData = new ArrayList<StationData>();
		for (StationDataIntermediateForm sdi : stationsData) {
			this.stationsData.add(sdi.getStationData());
		}
	}

	public void setSettings(SimulationSettings settings) {
		this.settings = settings;
	}

	public boolean isCompleted() {
		return isCompleted;
	}

	public void setCompleted(boolean isCompleted) {
		this.isCompleted = isCompleted;
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (getClass() != obj.getClass())
			return false;
		SimDataHolder other = (SimDataHolder) obj;
		if (name == null) {
			if (other.name != null)
				return false;
		} else if (!name.equals(other.name))
			return false;
		return true;
	}

	public double getAvgTime(Station src, Station end) {
		double time = times.getAvgTime(src, end);
		if (time > 0) {
			return StaticUtil.round(time);
		} else {
			List<Line> path=RouteTableService.getInstance().getPath(src, end);
			double d=0;
			for(Line line:path) {
				d=d+line.getLength();
			}
			double velocity=summary.getAvgVelocity();
			if(velocity>0) {
				return StaticUtil.round(d/velocity);
			} else {
				return StaticUtil.round(-1);
			}
		}
	}

	public LoadArray getLoad() {
		return load;
	}

	public String getName() {
		return name;
	}

	public long getRealTime() {
		return realTime;
	}

	public SimulationSettings getSettings() {
		return settings;
	}

	public long getStartTimeMs() {
		return startTimeMs;
	}

	public SummaryTripStats getSummary() {
		return summary;
	}

	public void setSummary(SummaryTripStats summary) {
		this.summary = summary;
	}

	public double getThroughputPerHour() {
		int noOfTicks = settings.getTimeResolutionPerSec() * 3600;
		if (tick == 0) {
			return StaticUtil.round(summary.getPassengersCarried());
		}
		return StaticUtil.round((summary.getPassengersCarried() * noOfTicks) / tick);
	}

	public int getTick() {
		return tick;
	}

	public String getTimeElapsedInHrMmSs() {
		int secsIn = tick / settings.getTimeResolutionPerSec();
		int hours = secsIn / 3600;
		int remainder = secsIn % 3600;
		int minutes = remainder / 60;
		int seconds = remainder % 60;
		return df2.format(hours) + ":" + df2.format(minutes) + ":" + df2.format(seconds);
	}

	public String getTimeElapsedInHrMmSsComputer() {
		if (startTimeMs == 0) {
			return "";
		}

		long milli = System.currentTimeMillis() - startTimeMs;
		long secsIn = milli / 1000;
		long hours = secsIn / 3600;
		long remainder = secsIn % 3600;
		long minutes = remainder / 60;
		long seconds = remainder % 60;
		return df2.format(hours) + ":" + df2.format(minutes) + ":" + df2.format(seconds);
	}

	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((name == null) ? 0 : name.hashCode());
		return result;
	}

	public void logPassengerExit(Passenger p, int tick) {
		if (!p.isCalled()) {
			times.addTime(p.getStart(), p.getEnd(), p.getTravelTime());
		}
		summary.logPodExit(p, tick);
	}

	public void logTime(int tick) {
		this.tick = tick;
	}

	public String printTimeMap() {
		return times.toString();
	}

	public void setName(String name) {
		this.name = name;
	}

	public void setStartTimeMs(long startTimeMs) {
		this.startTimeMs = startTimeMs;
	}

	public String toString() {
		return name;
	}

	public List<LineData> getLinesData() {
		for (LineData ld : linesData) {
			ld.getStat().load();
		}
		return linesData;
	}

	public List<StationData> getStationsData() {
		for (StationData sd : stationsData) {
			sd.getStat().load();
		}
		return stationsData;
	}

	public TimeGridData getTimes() {
		return times;
	}

	public StationDataIntermediateForm[] buildStationDataIntermediateForm() {
		List<StationDataIntermediateForm> list = new ArrayList<StationDataIntermediateForm>();
		for (StationData st : stationsData) {
			st.getStat().load();
			list.add(new StationDataIntermediateForm(st));
		}
		return list.toArray(new StationDataIntermediateForm[list.size()]);
	}

	public LineDataIntermediateForm[] buildLineDataIntermediateForm() {
		List<LineDataIntermediateForm> list = new ArrayList<LineDataIntermediateForm>();
		for (LineData ld : linesData) {
			ld.getStat().load();
			list.add(new LineDataIntermediateForm(ld));
		}
		return list.toArray(new LineDataIntermediateForm[list.size()]);
	}

}
