package com.instinct.service;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.StringReader;
import java.net.HttpURLConnection;
import java.net.URL;

import javax.xml.parsers.DocumentBuilderFactory;

import org.openstreetmap.gui.jmapviewer.Coordinate;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;
import org.xml.sax.InputSource;

public class HttpRequestor {

	private String getRequest(String url) throws Exception {
		URL obj = new URL(url);
		HttpURLConnection con = (HttpURLConnection) obj.openConnection();
		// optional default is GET
		con.setRequestMethod("GET");
		//add request header
		
		BufferedReader in = new BufferedReader(
		        new InputStreamReader(con.getInputStream()));
		String inputLine;
 
		StringBuffer response = new StringBuffer();
		while ((inputLine = in.readLine()) != null) {
			response.append(inputLine);
		}
		in.close();
 
		return response.toString();
	}
	
	
	private Coordinate getCoordinate(String xml) throws Exception {
		Document dom=DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(new InputSource(new StringReader(xml)));
		
		NodeList nl=dom.getElementsByTagName("COORDINATES");
		
		Element el=(Element)nl.item(0);
		String lat=el.getFirstChild().getTextContent();
		String lon=el.getChildNodes().item(1).getTextContent();
		Coordinate c=new Coordinate(Double.parseDouble(lat), Double.parseDouble(lon));
		return c;
	}
	
	public Coordinate doLookup(String addr) {
		Coordinate c=null;
		try {
		String a[]=addr.split(",");
		String url;
		if(a.length==2) {
			url="https://www.geocode.farm/v3/xml/forward/?addr="+a[0].trim()+"&country="+a[1].trim()+"&lang=en&count=1";
		} else {
			url="https://www.geocode.farm/v3/xml/forward/?addr="+a[0].trim()+"&country=USA&lang=en&count=1";
			
		}
		String xml=getRequest(url);
		c=getCoordinate(xml);
		} catch(Exception e) {
			e.printStackTrace();
			return null;
		}
		return c;
	}
	
	public static void main(String args[]) throws Exception {
		String ur="https://www.geocode.farm/v3/xml/forward/?addr=Kolkata";
		URL obj = new URL(ur);
		HttpURLConnection con = (HttpURLConnection) obj.openConnection();
		// optional default is GET
		con.setRequestMethod("GET");
		//add request header
		
		BufferedReader in = new BufferedReader(
		        new InputStreamReader(con.getInputStream()));
		String inputLine;
 
		StringBuffer response = new StringBuffer();
		while ((inputLine = in.readLine()) != null) {
			response.append(inputLine);
		}
		in.close();
 
		System.out.println(response.toString());
		
	}
}
