package com.instinct.objects.pod;

public enum Throttle {

	ACCELERATE("A"), BREAK("B");
	
	private final String code;

	Throttle(String code) {
		this.code=code;
	}
	
	public String toString() {
		return code;
	}
}
