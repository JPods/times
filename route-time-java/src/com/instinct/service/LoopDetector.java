package com.instinct.service;

import java.util.HashSet;
import java.util.Set;

import com.instinct.objects.network.Line;

public class LoopDetector {

	private Set<String> lines=new HashSet<String>();
	private boolean isOnLoop=false;
	
	public void offerLine(Line line) {
		if(lines.contains(line.getId())) {
			this.isOnLoop=true;
		} else {
			if(line.isPartOfTrafficCircle()) {
				if(lines.size()<20) {
					lines.add(line.getId());
				}
			}
		}
	}
	
	public boolean isOnLoop() {
		return isOnLoop;
	}
	
	public void reset() {
		isOnLoop=false;
		lines.clear();
	}
	
}
