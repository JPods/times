package com.instinct.gui.guactions;

import java.awt.Rectangle;
import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;

import javax.imageio.ImageIO;
import javax.swing.AbstractAction;
import javax.swing.JFileChooser;

import com.instinct.gui.GUIUtil;
import com.instinct.gui.MainFrame;
import com.instinct.gui.pad.Pad;
import com.instinct.gui.pad.SelectionManager;
import com.instinct.service.WorkspaceManager;

public class CaptureScreenAction extends AbstractAction {
	public CaptureScreenAction() {
		super("Capture Screen", GUIUtil.getImage("capture.png"));
		putValue(SHORT_DESCRIPTION, "Capture Screen");

		putValue(MNEMONIC_KEY, KeyEvent.VK_C);
		KeyBinder.getInstance().bind(KeyEvent.VK_C, this, "C");
	}

	public void actionPerformed(ActionEvent ae) {
		SelectionManager.getInstance().reset();

		Pad.getInstance().setCursorImage(null);

		File file = selectFile();
		if (file == null) {
			return;
		}

		Rectangle rect = MainFrame.getInstance().getBounds();

		try {
			String format = "png";
			BufferedImage captureImage = new BufferedImage(rect.width, rect.height, BufferedImage.TYPE_INT_ARGB);
			MainFrame.getInstance().paint(captureImage.getGraphics());

			ImageIO.write(captureImage, format, file);

			Pad.getInstance().showAlert("The screenshot saved");
		} catch (IOException ex) {
			ex.printStackTrace();
		}
	}
	
	private String getDefaultFile() {
		int index=1;
		for(File file:WorkspaceManager.getInstance().getCurrentNetworkDirectory().listFiles()) {
			if(file.getAbsolutePath().endsWith(".png") || file.getAbsolutePath().endsWith(".PNG")) {
				index++;
			}
		}
		
		String name=WorkspaceManager.getInstance().getCurrentNetworkDirectory().getName().replace(".jpd", "");
		
		return name+"-"+index;
	}

	private File selectFile() {
		JFileChooser fc = new JFileChooser();
		fc.setCurrentDirectory(WorkspaceManager.getInstance().getCurrentNetworkDirectory());
		fc.setSelectedFile(new File(getDefaultFile()));
		int ret = fc.showDialog(Pad.getInstance(), "Save");
		if (ret == JFileChooser.APPROVE_OPTION) {
			File sel = fc.getSelectedFile();
			if (!sel.getAbsolutePath().endsWith(".png")) {
				sel = new File(sel.getAbsoluteFile() + ".png");
			}
			return sel;
		}
		return null;
	}
}
