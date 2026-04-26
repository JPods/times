package com.instinct.service;

import java.math.BigDecimal;
import java.math.RoundingMode;

public class StaticUtil {

	public static double round(double value) {
		if(value==Double.NaN || Double.isInfinite(value)) {
			return value;
		}
		int places=2;
	    if (places < 0) throw new IllegalArgumentException();
	
	    BigDecimal bd = new BigDecimal(value);
	    bd = bd.setScale(places, RoundingMode.HALF_UP);
	    return bd.doubleValue();
	}

}
