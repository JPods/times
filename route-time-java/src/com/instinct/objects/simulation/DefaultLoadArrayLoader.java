package com.instinct.objects.simulation;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.instinct.objects.network.Station;

public class DefaultLoadArrayLoader implements LoadArrayLoader {

	private List<Station> stations;
	
	private Map<String, Integer> ind=new HashMap<String, Integer>();
	
	public DefaultLoadArrayLoader(Collection<Station> stations) {
		this.stations=new ArrayList<Station>(stations);
	}

	@Override
	public String getDestination(String src, int slot) {
		if(ind.containsKey(src)==false) {
			ind.put(src,0);
		}
		
		int index=ind.get(src);
		if(index==stations.size()) {
			index=0;
		}
		
		String dest=stations.get(index).getId();
		if(dest.equals(src)) {
			if(index==stations.size()-1) {
				index=0;
			} else {
				index++;
			}
			dest=stations.get(index).getId();
		}
		index++;
		ind.put(src, index);
		return dest;
	}

}
