package com.instinct.service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public class ThreadPoolService {
	private static int THREAD_POOL_SIZE=3;
	private ExecutorService executor = Executors.newFixedThreadPool(THREAD_POOL_SIZE);
	
	private List<Future> tasks=new ArrayList<Future>();
	
	public static ThreadPoolService instance=new ThreadPoolService();
	
	private ThreadPoolService() {
	}
	
	public static ThreadPoolService getInstance() {
		return instance;
	}

	public synchronized void submit(Runnable runnable) {
		Future f=executor.submit(runnable);
		tasks.add(f);
	}
	

	public synchronized void awaitTermination() {
		while(tasks.size()>0) {
			List<Future> finished=new ArrayList<Future>();
			for(Future f:tasks) {
				if(f.isDone()) {
					finished.add(f);
				}
			}
			tasks.removeAll(finished);
			finished.clear();
			try {
				Thread.sleep(2*100);
			} catch (InterruptedException e) {
				e.printStackTrace();
			}
		}
	}
}
