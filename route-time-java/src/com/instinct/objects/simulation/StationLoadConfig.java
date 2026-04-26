package com.instinct.objects.simulation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.xml.bind.annotation.XmlAccessType;
import javax.xml.bind.annotation.XmlAccessorType;
import javax.xml.bind.annotation.XmlElement;
import javax.xml.bind.annotation.XmlRootElement;
import javax.xml.bind.annotation.XmlTransient;

import com.instinct.objects.network.Station;
import com.instinct.service.WorkspaceManager;

@XmlRootElement
@XmlAccessorType(XmlAccessType.FIELD)
public class StationLoadConfig {

	@XmlElement
	private Map<String, Integer> toLoads=new HashMap<String, Integer>();
	
	@XmlTransient
	private List<String> list=new ArrayList<String>();
	
	@XmlTransient
	private final int SLOTS=360;
	
	@XmlTransient
	private boolean isInitialized=false;

	private int defaultLoad;
	
	public void setLoad(String id, int load) {
		toLoads.put(id, load);
		isInitialized=false;
		initialize();
	}
	
	public int getLoad(String srcId, String id) {
		initialize();
		if(srcId.equals(id)) {
			toLoads.put(id, 0);
			return 0;
		}
		if(!toLoads.containsKey(id)) {
			toLoads.put(id, defaultLoad);
		}
		return toLoads.get(id);
	}
	
	private void initialize() {
		if(isInitialized) {
			return;
		}
		int stationCnt=WorkspaceManager.getInstance().getNetwork().getAllStations().size();
		defaultLoad=(SLOTS-stationCnt)/stationCnt;
		list.clear();
		for(Station st:WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			list.add(st.getId());
		}

		List<String> t=	buildList();
		Collections.shuffle(t);
		int s=list.size();
		int r=SLOTS-s;
		r=r>=t.size()?t.size()-1:r;
		list.addAll(t.subList(0, r));
		
		for(int i=list.size();i<SLOTS;i++) {
			int random=(int)(Math.random()*stationCnt);
			String stId=list.get(random);
			list.add(stId);
		}
		isInitialized=true;
	}

	public String getDestionForSlot(int slot) {
		initialize();
		return list.get(slot);
	}
	
	private List<String> buildList() {
		List<String> t=new ArrayList<String>();
		for(Station st:WorkspaceManager.getInstance().getNetwork().getAllStations()) {
			String id=st.getId();
			addLoad(t,id,getLoad(id));
		}
		return t;
	}
	


	private int getLoad(String id) {
		if(toLoads.containsKey(id)) {
			return toLoads.get(id);
		}
		return defaultLoad;
	}

	private void addLoad(List<String> t,String id, int c) {
		for(int i=0;i<c;i++) {
			t.add(id);
		}
	}
	

}
