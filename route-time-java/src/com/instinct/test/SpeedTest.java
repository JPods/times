package com.instinct.test;

public class SpeedTest {

	public static void main(String args[]) {
		for (int i = 0; i < 20; i++) {
			m();
		}
	}

	private static void m() {
		int mega = 1024 * 1024;
		int fps = 240;
		int resolution =5;
		long LOOP = mega * fps * resolution;
		long m = 0, n = 0, f = 0;
		long startTime = System.currentTimeMillis();
		for (long i = 0; i < LOOP; i++) {
			m = i;
			n = m + n;
			f = n + i * (f - m);
		}

		long endTime = System.currentTimeMillis();
		System.out.println("m =" + m + ", n=" + n + ", f=" + f);
		System.out.println("Duration =" + ((double) (endTime - startTime)) / 1000);
	}
}
