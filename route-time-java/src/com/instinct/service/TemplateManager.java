package com.instinct.service;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import javax.swing.JOptionPane;

import org.jdom2.Document;
import org.jdom2.input.SAXBuilder;
import org.jdom2.output.XMLOutputter;

import com.instinct.gui.MainFrame;
import com.instinct.gui.Toolbar;
import com.instinct.service.serialization.SerializationService;

public class TemplateManager {

	private String templateDir = "templates";
	private SerializationService serializer = new SerializationService();

	private static TemplateManager instance=new TemplateManager();
	
	private String dir;
	public static TemplateManager getInstance() {
		return instance;
	}
	
	private TemplateManager() {
		try {
			dir=WorkspaceManager.getInstance().makeApplicationDirectory()+File.separator + templateDir;
			System.out.println("Path is:"+dir);
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	
	public Document getTemplateModel(String template) throws Exception {
		File file = new File(dir+ File.separator+ template + ".tld");
		SAXBuilder builder = new SAXBuilder();
		Document document = (Document) builder.build(file);
		return document;
	}

	
	
	

	public void saveAsTemplateFile() throws Exception {
		String templateName = (String) JOptionPane.showInputDialog(MainFrame.getInstance(), "Template Name", "Template Dialog", JOptionPane.PLAIN_MESSAGE);
		if(templateName==null || templateName.trim().length()==0) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Template name can't be null");
			return;
		}
		
		Set<String> existingNames=new HashSet<String>(getTemplateList());
		if(existingNames.contains(templateName)) {
			JOptionPane.showMessageDialog(MainFrame.getInstance(), "Name Already exists");
			return;
		}
		Document doc = serializer.serialize(WorkspaceManager.getInstance().getNetwork());
		File dirF = new File(dir);
		if (dirF.exists() == false) {
			dirF.mkdir();
		}
		FileOutputStream out = new FileOutputStream(dir + File.separator + templateName + ".tld", true);
		XMLOutputter serializer = new XMLOutputter();
		serializer.output(doc, out);
		out.flush();
		out.close();
		WorkspaceManager.getInstance().getNetwork().setDirty(false);
		Toolbar.getInstance().updateToolbar();
	}

	public List<String> getTemplateList() {
		List<String> list = new ArrayList<String>();
		File file = new File(dir);

		if (file.exists() == false) {
			return list;
		}

		for (String s : file.list()) {
			if (s.endsWith(".tld") && s.trim().length()>4) {
				list.add(s.substring(0, s.length() - 4));
			}
		}
		Collections.sort(list);
		return list;
	}

	public void deleteTemplate(String templateName) {
		File file = new File(dir+ File.separator + templateName + ".tld");
		file.delete();
	}
	
	public String getTemplateDir() {
		if(dir==null) {
			return "";
		} else {
			return dir.replace("\\.\\", "\\");
		}
	}
	
	

	
}