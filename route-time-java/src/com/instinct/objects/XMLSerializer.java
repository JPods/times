package com.instinct.objects;

import org.jdom2.Element;

public interface XMLSerializer<T> {

	static final String LAT="lat";
	static final String LON="lon";
	static final String ID="ID";
	static final String SWITCH= "Switch";
	static final String STATION="Station";
	static final String IS_NETWORK_EL="isNetworkElement";
	
	public Element serialize(T t);
	
	public T deserialize(Element e);
}
