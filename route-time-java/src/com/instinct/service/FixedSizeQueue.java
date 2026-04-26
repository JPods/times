package com.instinct.service;

import java.util.ArrayList;

public class FixedSizeQueue<K> extends ArrayList<K> {

    private int maxSize;
	private K lastAdded;

    public FixedSizeQueue(int size){
        this.maxSize = size;
    }

    public boolean add(K k){
        boolean r = super.add(k);
        if (size() > maxSize){
            removeRange(0, size() - maxSize - 1);
        }
        lastAdded=k;
        return r;
    }
    
    public String toString() {
    	StringBuilder sb=new StringBuilder();
    	for(int c=0,i=this.size()-1;i>=0 && c<30;i--,c++) {
    		sb.append(this.get(i).toString());
    		sb.append("\n");
    	}
    	return sb.toString();
    }
    
    public K getLastAdded() {
    	return lastAdded;
    }
}