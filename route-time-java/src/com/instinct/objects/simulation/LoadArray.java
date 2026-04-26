package com.instinct.objects.simulation;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

import com.instinct.objects.network.Station;

public class LoadArray {

	private static final int SLOT=360; //One passenger comes every 10 sec in each of the station
	
	private String [][]loadTbl=null;
	
	private String[] stationsIndex=null;
	
	private Map<String,Integer> indexes=new HashMap<String,Integer>();
	
	
	public void init(Collection<Station> stations, LoadArrayLoader loader) { 
		loadTbl=new String[stations.size()][SLOT];
		stationsIndex=new String[stations.size()];
		
		int stationIndex=0;
		for(Station src:stations) {
			stationsIndex[stationIndex]=src.getId();
			loadTbl[stationIndex]=new String[SLOT];
			for(int i=0;i<SLOT;i++) {
				String dst=loader.getDestination(src.getId(), i);
				loadTbl[stationIndex][i]=dst;
			}
			stationIndex++;
		}
	}


	public String getDestination(String stId, int slot) {
		int index=0;
		if(indexes.containsKey(stId)) {
			index=indexes.get(stId);
		} else {
			index=getIndex(stId);
			indexes.put(stId, index);
		}
		
		return loadTbl[index][slot];
	}


	private int getIndex(String stId) {
		for(int i=0;i<stationsIndex.length;i++) {
			if(stationsIndex[i].equals(stId)) {
				return i;
			}
		}
		return -1;
	}


	public void setDestination(String stId, int slot, String destId) {
		int index=indexes.get(stId);
		loadTbl[index][slot]=destId;
	}


	public void setLoadTbl(String[][] loadTbl) {
		this.loadTbl = loadTbl;
	}


	public void setStationsIndex(String[] stationsIndex) {
		this.stationsIndex = stationsIndex;
	}
	
	

}
