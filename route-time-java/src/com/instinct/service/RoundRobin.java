package com.instinct.service;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class RoundRobin<T> {

	private Map<T,List<Count<T>>> counter=new HashMap<T,List<Count<T>>>();
	private Collection<T> sts=null;
	
	public RoundRobin(Collection<T> sts) {
		this.sts=sts;
	}
	
	public  T peekNext(T st) {
		if(!counter.containsKey(st)) {
			counter.put(st,  getCountList(st));
		}
		
		Count<T> least=null;
		for(Count<T> c:counter.get(st)) {
			if(least==null || least.getCnt()>c.getCnt()) {
				least=c;
			}
		}
		return least.get(st);

	}

	private List<Count<T>> getCountList(T st) {
		List<Count<T>> list=new ArrayList<Count<T>>();
		
		for(T s:sts) {
			if(!s.equals(st)) {
				list.add(new Count<T>(s));
			}
		}
		return list;
	}
}


class Count<T> {

	private T st;
	private int cnt;
	private Set<T> src=new HashSet<T>();
	public Count(T st) {
		this.st=st;
	}
	
	public T get(T s) {
		src.add(s);
		cnt++;
		return st;
	}

	public synchronized int getCnt() {
		return cnt;
	}
	
	public String toString() {
		StringBuilder sb=new StringBuilder();
		
		sb.append(st);
		sb.append(":");
		
		for(T s:src) {
			sb.append(s);
			sb.append(",");
		}
		
		return sb.toString();
	}
}
