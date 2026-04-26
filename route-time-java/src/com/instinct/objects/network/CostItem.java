package com.instinct.objects.network;

public class CostItem {

	private String name;
	private int price;
	private int unit;
	
	
	public String getName() {
		return name;
	}
	public int getPrice() {
		return price;
	}
	public double getUnit() {
		return unit;
	}
	public double getTotal() {
		return price*unit;
	}
	public CostItem(String name, int price, int unit) {
		super();
		this.name = name;
		this.price = price;
		this.unit = unit;
	}
	
	
	
}
