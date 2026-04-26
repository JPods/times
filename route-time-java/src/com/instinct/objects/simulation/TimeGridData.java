package com.instinct.objects.simulation;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.instinct.objects.network.Network;
import com.instinct.objects.network.Station;
import com.instinct.service.WorkspaceManager;

public class TimeGridData {

	private Map<Station, Map<Station, TimeHolder>> time=new HashMap<Station, Map<Station, TimeHolder>>();
	private int cnt=0;
	
	public TimeGridData(TimeGridJson obj) {
		Network net=WorkspaceManager.getInstance().getNetwork();
		for(IntermediateForm f:obj.getTimes()) {
			Station dest=(Station)net.getNode(f.getDestinationId());
			Station src=(Station)net.getNode(f.getSrcId());
			if(time.containsKey(dest)==false) {
				time.put(dest, new HashMap<Station,TimeHolder>());
			}
			time.get(dest).put(src, new TimeHolder(f.getAvgTime()));
		}
	}
	
	public TimeGridData() {
	}
	
	
	public double getAvgTime(Station src, Station end) {
	
		Map<Station, TimeHolder> map=time.get(end);
		TimeHolder ret=null;
		if(map!=null) {
			ret=map.get(src);
		}
		
		if(ret==null) {
			return -1;
		}
		return ret.getAvgTime();
	}
	
	public void addTime(Station src, Station end, double t) {
		cnt++;
		if(!time.containsKey(end)) {
			time.put(end, new HashMap<Station, TimeHolder>());
		}
		//Just to be sure no src is left
		if(!time.containsKey(src)) {
			time.put(src, new HashMap<Station, TimeHolder>());
		}
		Map<Station, TimeHolder> m=time.get(end);
		if(m==null) {
			return;
		}
		if(!m.containsKey(src)) {
			TimeHolder th=new TimeHolder();
			m.put(src, th);
			th.addTime(t);
		} else {
			m.get(src).addTime(t);
		}
		
	}

	public String toString() {
		StringBuilder sb=new StringBuilder();
		for(Station st:time.keySet()) {
			sb.append(st.getId()+": ");
			for(Station st1:time.get(st).keySet()) {
				sb.append(st1.getId());
				sb.append("(");
				sb.append((int)time.get(st).get(st1).getAvgTime());
				sb.append("), ");
			}
		}
		return sb.toString();
	}
	
	public Collection<IntermediateForm> getIntermediateForm() {
		List<IntermediateForm> arrays=new ArrayList<IntermediateForm>();
		for(Map.Entry<Station, Map<Station, TimeHolder>> e1:time.entrySet()) {
			for( Map.Entry<Station, TimeHolder> e2:e1.getValue().entrySet()) {
				IntermediateForm data=new IntermediateForm(e1.getKey().getId(), e2.getKey().getId(), e2.getValue().getAvgTime());
				arrays.add(data);
			}
		}
		return arrays;
	}

	public boolean checkValid() {
		Set<Station> thisSet=new HashSet<Station>();
		thisSet.addAll(time.keySet());
		
		Set<Station> otherSet=new HashSet<Station>();
		otherSet.addAll(WorkspaceManager.getInstance().getNetwork().getAllStations());
		
		if(thisSet.containsAll(otherSet) && otherSet.containsAll(thisSet)) {
			return true;
		}
		return false;
	}
}

