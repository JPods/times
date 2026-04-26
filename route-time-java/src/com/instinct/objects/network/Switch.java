package com.instinct.objects.network;

public interface Switch extends Node {

	void attachEntryLine(Line line);
	
	void detachEntryLine(Line line);
	
	void attachExitLine(Line line);
	
	void detachExitLine(Line line);
	
	int getEntryCount();
	
	int getExitCount();

	
	Line getEntry1();
	
	Line getExit1();
	
	Line getEntry2();
	
	Line getExit2();
	
	Line getEntry();
	
	Line getExit();
	
	Line getOtherEntry(Line l);
	
	Line getOtherExit(Line l);

	boolean checkValidEntry();
	
	boolean checkValidExit();

	public boolean isNetworkElement();
	
	public void setNetworkElement(boolean isNetworkElement);
	
}
