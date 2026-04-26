package com.instinct.gui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Desktop;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.net.URI;

import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingConstants;
import javax.swing.border.Border;
import javax.swing.border.EmptyBorder;

public class AboutDisplay extends JDialog {

	private static final String ver="1.2.1";
	public AboutDisplay() {
		setTitle("Contact Us");
		this.setIconImage(GUIUtil.getImage("icon.png").getImage());
		JPanel container = new JPanel();
		container.setLayout(new BoxLayout(container, BoxLayout.X_AXIS));
		String initialText = "<html>\n<font color=green size=+2>Bill James</font><br>"
				+ "<font >bill.james@jpods.com</font><br><br>"
				+ "<font color=green size=+2>Sourish Chanda</font><br>\n" + "<font >sourish.chanda@gmail.com</font><br>";
		JLabel txt = new JLabel(initialText);
		Border margin = new EmptyBorder(10, 20, 10, 20);
		txt.setBorder(margin);
		this.add(BorderLayout.CENTER, txt);

		final String url = "http://www.jpods.com";
		String linkHtml = "<html><a align='center'><font color=blue>www.jpods.com</font></a>";
		JButton btnNorth = new JButton(linkHtml);
		margin = new EmptyBorder(10, 20, 10, 20);
		btnNorth.setBorder(margin);
		btnNorth.setHorizontalAlignment(SwingConstants.CENTER);
		btnNorth.setBorderPainted(false);
		btnNorth.setOpaque(false);
		btnNorth.setBackground(Color.WHITE);
		btnNorth.setToolTipText(url);

		this.add(BorderLayout.NORTH, btnNorth);

		btnNorth.addActionListener(new ActionListener() {

			@Override
			public void actionPerformed(ActionEvent ae) {
				if (Desktop.isDesktopSupported()) {
					try {
						Desktop.getDesktop().browse(new URI(url));
					} catch (Exception e) { /* TODO: error handling */
					}
				} else { /* TODO: error handling */
				}

			}
		});

		JLabel lblSouth=new JLabel("<html><font color=black size=>Route-Time @ Ver. "+ver+"</font><br>");
		margin = new EmptyBorder(20, 45, 20, 20);
		lblSouth.setBorder(margin);
		this.add(BorderLayout.SOUTH, lblSouth);
		
		this.setModal(true);
		pack();
		setLocationRelativeTo(null);
	}
}
