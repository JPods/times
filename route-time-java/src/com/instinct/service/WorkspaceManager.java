package com.instinct.service;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.FileWriter;
import java.net.URI;
import java.net.URL;
import java.net.URLDecoder;
import java.security.CodeSource;

import javax.swing.JFileChooser;
import javax.swing.JOptionPane;
import javax.swing.filechooser.FileNameExtensionFilter;

import org.jdom2.Document;
import org.jdom2.input.SAXBuilder;
import org.jdom2.output.XMLOutputter;

import com.google.gson.Gson;
import com.google.gson.stream.JsonReader;
import com.instinct.gui.MainFrame;
import com.instinct.gui.Toolbar;
import com.instinct.gui.pad.Pad;
import com.instinct.objects.network.Network;
import com.instinct.objects.simulation.SimDataHolder;
import com.instinct.objects.simulation.SimulationSettings;
import com.instinct.service.serialization.SerializationService;

public class WorkspaceManager {

	private File applicationDirectory;
	private File currentNetworkDirectory;
	private String currentlySelectedFile;
	private Network net = null;
	private SimDataHolder workingSim;
	

	private SerializationService serializer = new SerializationService();

	private static WorkspaceManager instance = new WorkspaceManager();

	public static WorkspaceManager getInstance() {
		return instance;
	}

	public File getApplicationDirectory() {
		return applicationDirectory;
	}

	private WorkspaceManager() {
		workingSim = new SimDataHolder();
		try {
			applicationDirectory = new File(makeApplicationDirectory());
			this.net = new Network("Untitled");
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public String makeApplicationDirectory() throws Exception {
//		if (isMac()) {
//			System.out.println("It's a Mac");
//			String dirPath = "/Applications/JPODS";
//			System.out.println("Application Directory:"+(new File(".").getAbsolutePath()));
//			return dirPath;
//		}
		String str=new File(".").getAbsolutePath();
		return str.substring(0,str.length()-2);
	}

	private boolean isMac() {
		String os = System.getProperty("os.name");
		if (os.toUpperCase().contains("MAC")) {
			return true;
		}
		return false;
	}

	public boolean isSaved() {
		return currentlySelectedFile != null;
	}

	public void saveFile() {
		if (currentlySelectedFile == null) {
			saveAsFile();
			return;
		}
		try {
			save(new File(currentlySelectedFile));
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public void setWorkingSim(SimDataHolder simDataHolder) {
		this.workingSim = simDataHolder;
	}

	public File getCurrentNetworkDirectory() {
		return currentNetworkDirectory;
	}

	private void askForSave() {
		Network n = getNetwork();
		if (n == null) {
			return;
		}
		if (!n.isDirty()) {
			return;
		}
		n.setVersionId(System.currentTimeMillis());
		int ret = JOptionPane.showConfirmDialog(MainFrame.getInstance(), "Do you want to Save changes?");
		if (ret == JOptionPane.OK_OPTION) {
			saveAsFile();
		}
	}

	public void openFile() {
		askForSave();
		JFileChooser fc = new JFileChooser(applicationDirectory);
		FileNameExtensionFilter filter = new FileNameExtensionFilter("PRT network descriptors- jpd", "jpd");
		fc.setFileFilter(filter);
		int ret = fc.showOpenDialog(Pad.getInstance());
		if (ret == JFileChooser.APPROVE_OPTION) {
			File sel = fc.getSelectedFile();
			openFile(sel);
		}
	}

	public void openFile(File sel) {
		this.currentlySelectedFile = sel.getAbsolutePath();
		this.currentNetworkDirectory = new File(sel.getAbsolutePath().replace(".jpd", ""));

		if (currentNetworkDirectory.exists() == false) {
			currentNetworkDirectory.mkdir();
		}
		MainFrame.getInstance().setTitle(sel.getPath());
		try {
			loadNetwork(sel);
			workingSim.initialize();
			SimulationSettings settings = loadSimSettings();
			if (settings != null) {
				workingSim.setSettings(settings);
			}
			Pad.getInstance().notifyComponents();
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public void newFile() {
		askForSave();
		this.currentlySelectedFile = null;
		this.currentNetworkDirectory = null;
		String title = "Untitled";
		createNetwork(title);
		MainFrame.getInstance().setTitle(title);
		Pad.getInstance().notifyComponents();
	}

	public void clearNetwork() {
		int ret = JOptionPane.showConfirmDialog(MainFrame.getInstance(), "Clear Network?");
		if (ret != JOptionPane.OK_OPTION) {
			return;
		}
		getNetwork().clear();
		MainFrame.getInstance().setTitle("PRT Demonstration Application");
		Pad.getInstance().notifyComponents();
	}

	public void saveAsFile() {
		JFileChooser fc = new JFileChooser(applicationDirectory);
		FileNameExtensionFilter filter = new FileNameExtensionFilter("PRT network descriptors- jpd", "jpd");
		fc.setFileFilter(filter);
		int ret = fc.showDialog(Pad.getInstance(), "Save");
		if (ret == JFileChooser.APPROVE_OPTION) {
			File sel = fc.getSelectedFile();
			File dir = new File(sel.getName());
			MainFrame.getInstance().setTitle(sel.getPath());
			if (!sel.getAbsolutePath().endsWith(".jpd")) {
				sel = new File(sel.getAbsoluteFile() + ".jpd");
			}
			try {
				save(sel);
				this.currentlySelectedFile = sel.getAbsolutePath();
				dir.mkdir();
				this.currentNetworkDirectory = dir;
			} catch (Exception e) {
				e.printStackTrace();
			}
		}
	}

	public void createNetwork(String name) {
		net = new Network(name);
	}

	public Network getNetwork() {
		return net;
	}

	public SimDataHolder getWorkingSim() {
		return workingSim;
	}

	public String getCurrentlySelectedFile() {
		return currentlySelectedFile;
	}

	public String getValidationString() {
		NetworkValidator validator = new NetworkValidator();
		return validator.getValidationString();
	}

	private void loadNetwork(File sel) throws Exception {
		SAXBuilder builder = new SAXBuilder();
		Document document = (Document) builder.build(sel);
		serializer.deserialize(document);
		net.computeMapCenter();
		Pad.getInstance().setDisplayPositionByLatLon(net.getLat(), net.getLon(), 14);
		net.setDirty(false);
		Pad.getInstance().notifyComponents();
		Toolbar.getInstance().updateToolbar();
		this.currentlySelectedFile = sel.getPath();

	}

	private SimulationSettings loadSimSettings() throws Exception {
		System.out.println("Load Sim Settings is called");
		String file = currentNetworkDirectory.getAbsolutePath() + File.separator + "settings.json";
		System.out.println("Loading settings from file:"+file);
		File fileObj = new File(file);
		if (fileObj.exists() == false) {
			return null;
		}
		FileReader fw = new FileReader(file);
		BufferedReader reader = new BufferedReader(fw);
		Gson gson = new Gson();
		JsonReader jsonReader = new JsonReader(reader);
		jsonReader.setLenient(true);
		SimulationSettings ss = gson.fromJson(jsonReader, SimulationSettings.class);
		reader.close();
		

		return ss;
	}

	private void save(File sel) throws Exception {
		Network n = getNetwork();
		if (!n.isDirty()) {
			return;
		}
		n.setVersionId(System.currentTimeMillis());

		this.currentlySelectedFile = sel.getPath();
		Document doc = serializer.serialize(net);
		FileOutputStream out = new FileOutputStream(sel);
		XMLOutputter serializer = new XMLOutputter();
		serializer.output(doc, out);
		out.flush();
		out.close();
		net.setDirty(false);
		if (workingSim == null) {
			workingSim = new SimDataHolder();
		}
		workingSim.initialize();
		Toolbar.getInstance().updateToolbar();

	}

	public boolean checkTime(int time) {
		if (time < getWorkingSim().getSettings().getTimeResolutionPerSec() * 3600) {
			return true;
		}
		return false;
	}

	public void saveSimulationSettings(SimulationSettings cfg) throws Exception {
		System.out.println("Inside Simulation Settings Save Action");
		String fileName = currentNetworkDirectory.getAbsolutePath() + File.separator+"settings.json";
		System.out.println("Name:"+fileName);
		File file = new File(fileName);
		if (file.exists()) {
			System.out.println("file exists");
			file.delete();
			Thread.sleep(1000);
		}
		file.createNewFile();
		System.out.println("New file created");
		FileWriter fw = new FileWriter(fileName, true);
		BufferedWriter bw = new BufferedWriter(fw);
		Gson gson = new Gson();
		String str = gson.toJson(cfg);
		bw.write(str);
		bw.close();
		System.out.println("File written");
		System.out.println("End of method call");
	}

	public double getGraceDistance() {
		if(workingSim==null) {
			return 0;
		} else {
			return workingSim.getSettings().getGraceDistance();
		}
	}

}
