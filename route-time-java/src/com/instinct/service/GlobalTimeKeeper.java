package com.instinct.service;

import java.util.concurrent.atomic.AtomicInteger;

public class GlobalTimeKeeper  {

	private static GlobalTimeKeeper instance=new GlobalTimeKeeper();
	
	
	private AtomicInteger clock=new AtomicInteger(0);
	
	private GlobalTimeKeeper() {
	}
	
	public static GlobalTimeKeeper getInstance() {
		return instance;
	}
	
	
	public int tick() {
		return clock.getAndIncrement();
	}

	public int getTime() {
		return clock.get();
	}
	
	public void reset() {
		clock.set(0);
	}
}
