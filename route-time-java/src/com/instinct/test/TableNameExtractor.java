package com.instinct.test;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class TableNameExtractor {

	
	public static void main(String args[]) throws Exception  {
		File f=new File("C:\\FieldData.txt");
		
		BufferedReader br=new BufferedReader(new FileReader(f));
		
		String line =br.readLine();
		List<String> lines=new ArrayList<String>();
		while(line!=null) {
			lines.add(line);
			line=br.readLine();
		}
		
		List<String> tableNames=new ArrayList<String>();
		for(int i=0;i<lines.size();i++) {
			if(lines.get(i).contains("**_TableNum")) {
				String tableName=lines.get(i-1);
				if(tableName.contains("zz")==false && tableName.contains("ZZ")==false) {
					tableNames.add(tableName.replace("**_", ""));
				}
			}
		}
		Collections.sort(tableNames);
		for(String s:tableNames) {
			System.out.println(s);
		}
	}
}
