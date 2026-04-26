package com.instinct.objects.network;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import com.instinct.objects.pod.Pod;
import com.instinct.service.GlobalTimeKeeper;

public class PodQueue implements  Serializable {

	private static final long serialVersionUID = 1L;
	private List<Pod> list=null;
	
	private AtomicInteger totalPodsEntered=new AtomicInteger(0);
	private AtomicInteger totalPodsExited=new AtomicInteger(0);
	private AtomicInteger totalTimeSpend=new AtomicInteger(0);
	
	private int capacity=0;
	private Map<String, Integer> entryTimes=new HashMap<String, Integer>();
	private int timeStayed;

	public PodQueue(int size) {
		list=Collections.synchronizedList(new ArrayList<Pod>(size));
		capacity=size;

	}

	
	
	public void setTimeStayed(int timeStayed) {
		this.timeStayed = timeStayed;
	}



	public synchronized int getCapacity() {
		return capacity;
	}
	
	public synchronized boolean isFull() {
		if(list.size()==capacity) {
			return true;
		}
		return false;
	}
	
	public synchronized void addPod(Pod pod) {
		if(pod==null) {
			return;
		}
		totalPodsEntered.incrementAndGet();
		list.add(pod);
		entryTimes.put(pod.getId(), pod.getLastUpdatedTime());
	}
	

	public synchronized int totalTraffic() {
		return list.size();
	}

	public synchronized boolean isFrontPod(Pod pod) {
		if(list.size()>0 && list.indexOf(pod)==0) {
			return true;
		}
		return false;
	}

	public synchronized boolean isTailPod(Pod pod) {
		if(list.indexOf(pod)==list.size()-1) {
			return true;
		}
		
		return false;
	}

	public synchronized Pod removePod() {
		if(list.size()>0) {
			Pod pod=list.remove(0);
			int exitTime=GlobalTimeKeeper.getInstance().getTime();
			if(entryTimes.containsKey(pod.getId())) {
				timeStayed=exitTime-entryTimes.get(pod.getId());
				totalTimeSpend.addAndGet(timeStayed);
			}
			entryTimes.remove(pod.getId());
			totalPodsExited.incrementAndGet();
			return pod;
		}
		return null;
	}


	public synchronized Pod getPodAhead(Pod pod) {
		int pos = list.indexOf(pod);
		if(pos>=1) {
			return list.get(pos-1);
		}
		return null;
	}

	public int getLatestTimeStayed() {
		return timeStayed;
	}

	public synchronized int getPodPosition(Pod pod) {
		return list.indexOf(pod);
	}

	public synchronized int getTotalNosOfPods() {
		return size();
	}

	public synchronized Pod getTailPod() {
		if(list.size()==0) {
			return null;
		} else {
			return list.get(list.size()-1);
		}
	}

	public synchronized Pod getHeadPod() {
		if(list.size()==0) {
			return null;
		} else {
			return list.get(0);
		}	}

	public synchronized Pod getPodByPos(int pos) {
		return list.get(pos);
	}

	public synchronized List<Pod> getAll() {
		List<Pod> pods=new ArrayList<Pod>(list.size());
		
		for(int i=0;i<list.size();i++) {
			pods.add(list.get(i));
		}
		return pods;
	}

	public synchronized int size() {
		return list.size();
	}
	
	public synchronized boolean contains(Pod p) {
		return list.contains(p);
	}

	public synchronized void clear() {
		list.clear();
	}

	public synchronized int getTotalPodsExited() {
		return totalPodsExited.get();
	}

	public synchronized double getAvgTimeSpend() {
		if(totalPodsExited.get()==0) {
			return 0;
		}
		return totalTimeSpend.get()/totalPodsExited.get();
	}
	
	public synchronized int getTotalPodsEntered() {
		return totalPodsEntered.get();
	}	
	


}
