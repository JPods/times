package com.instinct.gui;

import java.awt.Component;
import java.awt.Cursor;
import java.awt.Dimension;
import java.util.ArrayList;
import java.util.List;

import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JPanel;
import javax.swing.JTabbedPane;
import javax.swing.event.ChangeEvent;
import javax.swing.event.ChangeListener;

import com.instinct.gui.guactions.AboutAction;
import com.instinct.gui.guactions.AddCircleAction;
import com.instinct.gui.guactions.AddDoubleLineAction;
import com.instinct.gui.guactions.AddFenceAction;
import com.instinct.gui.guactions.AddGroupAction;
import com.instinct.gui.guactions.AddLineAction;
import com.instinct.gui.guactions.AddSwitchAction;
import com.instinct.gui.guactions.CaptureScreenAction;
import com.instinct.gui.guactions.CitySearchAction;
import com.instinct.gui.guactions.ClearNetworkAction;
import com.instinct.gui.guactions.DeleteTemplateAction;
import com.instinct.gui.guactions.MarkStationAction;
import com.instinct.gui.guactions.MergeLoadAction;
import com.instinct.gui.guactions.NewNetworkAction;
import com.instinct.gui.guactions.OpenAction;
import com.instinct.gui.guactions.RoutesAction;
import com.instinct.gui.guactions.SaveAction;
import com.instinct.gui.guactions.SaveAsAction;
import com.instinct.gui.guactions.SaveAsTemplateAction;
import com.instinct.gui.guactions.SaveSimulationAction;
import com.instinct.gui.guactions.ShowEnergySavingAction;
import com.instinct.gui.guactions.ShowPodLogAction;
import com.instinct.gui.guactions.ShowResultAction;
import com.instinct.gui.guactions.ShowSimSettingAction;
import com.instinct.gui.guactions.ShowSlotFormAction;
import com.instinct.gui.guactions.ShowStationZoomAction;
import com.instinct.gui.guactions.ShowTimeGridAction;
import com.instinct.gui.guactions.ShowTimeMapAction;
import com.instinct.gui.guactions.StartStopSimAction;
import com.instinct.gui.pad.Pad;
import com.instinct.service.SimulationManager;
import com.instinct.service.TimeGraphMouseHandler;
import com.instinct.service.WorkspaceManager;

public class Toolbar extends JPanel {

	private JButton newBtn = new JButton(new NewNetworkAction());
	private JButton openBtn = new JButton(new OpenAction());
	private JButton saveAsBtn = new JButton(new SaveAsAction());
	private JButton saveBtn = new JButton(new SaveAction());

	private JButton fenceBtn = new JButton(new AddFenceAction());
	private JButton switchBtn = new JButton(new AddSwitchAction());
	private JButton lineBtn = new JButton(new AddLineAction());
	private JButton doubleLineBtn = new JButton(new AddDoubleLineAction());
	private JButton stBtn = new JButton(new MarkStationAction());
	private JButton tcBtn = new JButton(new AddCircleAction());
	private JButton groupBtn = new JButton(new AddGroupAction());
	private JButton clearBtn = new JButton(new ClearNetworkAction());
	private JButton citySearchBtn = new JButton(new CitySearchAction());

	private JButton routeBtn = new JButton(new RoutesAction());
	private JButton aboutBtn = new JButton(new AboutAction());


	private JButton simBtn = new JButton(new ShowSimSettingAction());
	private JButton slotBtn = new JButton(new ShowSlotFormAction());
	private JButton startStopSimBtn = new JButton(new StartStopSimAction());
	private JButton saveSimBtn = new JButton(new SaveSimulationAction());
	private JButton stZoomBtn = new JButton(new ShowStationZoomAction());
	private JButton timeBtn = new JButton(new ShowTimeGridAction());
	private JButton timeMapBtn = new JButton(new ShowTimeMapAction());
	private JButton resultBtn = new JButton(new ShowResultAction());
	//private JButton mergeLoadBtn = new JButton(new MergeLoadAction());
	private JButton podBtn = new JButton(new ShowPodLogAction());
	private JButton showEnergySavingsBtn = new JButton(new ShowEnergySavingAction());
	private JButton captureScreenBtn = new JButton(new CaptureScreenAction());

	private JButton saveTemplateBtn = new JButton(new SaveAsTemplateAction());
	private JButton deleteTemplateBtn = new JButton(new DeleteTemplateAction());

	private JButton currentlyPressedBtn;

	private JTabbedPane tab = new JTabbedPane();

	private static Toolbar instance = new Toolbar();

	private final JPanel designPane = new JPanel();

	private final Component separator = Box.createRigidArea(new Dimension(5, 5));

	private List<JButton> templateBtns=new ArrayList<JButton>();
	public static Toolbar getInstance() {
		return instance;
	}

	private Toolbar() {
		this.setLayout(new BoxLayout(this, BoxLayout.X_AXIS));
		layoutDesignPane();
		tab.addTab("Design", designPane);

		JPanel simPane = addSimulationPanel();
		tab.addTab("Simulation", simPane);

		this.add(tab);

		tab.addChangeListener(new ChangeListener() {
			@Override
			public void stateChanged(ChangeEvent e) {
				setCursor(Cursor.getPredefinedCursor(Cursor.WAIT_CURSOR));
				MainFrame.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.WAIT_CURSOR));
				Pad.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.WAIT_CURSOR));

				if (tab.getSelectedIndex() == 0) {
					if(SimulationManager.getInstance().isSimulationRunning()) {
						Pad.getInstance().showAlert("You must stop the Simulation before going to the Design tab");
						tab.setSelectedIndex(1);
					}
					StatusBar.getInstance().designMode();
					designPane.remove(separator);
					designPane.add(separator);
					TimeGraph.getInstance().setVisible(false,null);
					Pad.getInstance().removeMouseListener(TimeGraphMouseHandler.getInstance());
					Pad.getInstance().setCursor(new Cursor(Cursor.DEFAULT_CURSOR));
				} else {
					if (WorkspaceManager.getInstance().isSaved()==false) {
						Pad.getInstance().showAlert("You must save network to move to the Simulation tab");
						tab.setSelectedIndex(0);
						setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
						MainFrame.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
						Pad.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
						return;
					}
					StatusBar.getInstance().simulateMode();
					designPane.remove(separator);
				}
				setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
				MainFrame.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
				Pad.getInstance().setCursor(Cursor.getPredefinedCursor(Cursor.DEFAULT_CURSOR));
			}
		});
		
	}

	private void layoutDesignPane() {
		designPane.setLayout(new BoxLayout(designPane, BoxLayout.Y_AXIS));
		JPanel topRowBtnPane = new JPanel();
		topRowBtnPane.setLayout(new BoxLayout(topRowBtnPane, BoxLayout.X_AXIS));

		topRowBtnPane.add(newBtn);
		topRowBtnPane.add(openBtn);
		topRowBtnPane.add(saveBtn);
		topRowBtnPane.add(saveAsBtn);
		topRowBtnPane.add(Box.createHorizontalGlue());

		topRowBtnPane.add(fenceBtn);
		topRowBtnPane.add(switchBtn);
		topRowBtnPane.add(stBtn);
		topRowBtnPane.add(lineBtn);
		topRowBtnPane.add(doubleLineBtn);
		topRowBtnPane.add(tcBtn);
		topRowBtnPane.add(groupBtn);
		topRowBtnPane.add(clearBtn);
		topRowBtnPane.add(Box.createHorizontalGlue());
		topRowBtnPane.add(saveTemplateBtn);
		topRowBtnPane.add(deleteTemplateBtn);
		topRowBtnPane.add(Box.createHorizontalGlue());
		topRowBtnPane.add(citySearchBtn);
		topRowBtnPane.add(routeBtn);
		topRowBtnPane.add(Box.createHorizontalGlue());
		topRowBtnPane.add(aboutBtn);

		designPane.add(topRowBtnPane);
		designPane.add(separator);
		updateToolbar();
	}

	private JPanel addSimulationPanel() {
		JPanel simPanel = new JPanel();

		simPanel.setLayout(new BoxLayout(simPanel, BoxLayout.X_AXIS));
		simPanel.add(simBtn);
		simPanel.add(slotBtn);
		simPanel.add(startStopSimBtn);
		simPanel.add(saveSimBtn);
		simPanel.add(stZoomBtn);
		simPanel.add(timeBtn);
		simPanel.add(timeMapBtn);
		simPanel.add(resultBtn);
		//simPanel.add(mergeLoadBtn);
		simPanel.add(podBtn);
		simPanel.add(showEnergySavingsBtn);
		simPanel.add(captureScreenBtn);

		return simPanel;
	}

	public void resetBtn() {
		if (currentlyPressedBtn != null) {
			currentlyPressedBtn.setEnabled(true);
		}
	}

	public void disableAllButtons() {
		newBtn.setEnabled(false);
		openBtn.setEnabled(false);
		saveAsBtn.setEnabled(false);
		saveBtn.setEnabled(false);
		fenceBtn.setEnabled(false);
		switchBtn.setEnabled(false);
		lineBtn.setEnabled(false);
		doubleLineBtn.setEnabled(false);
		stBtn.setEnabled(false);
		tcBtn.setEnabled(false);
		groupBtn.setEnabled(false);
		clearBtn.setEnabled(false);
		citySearchBtn.setEnabled(false);
		
		routeBtn.setEnabled(false);
		saveTemplateBtn.setEnabled(false);
		
		enableTemplatesBtns(false);
	}
	
	public void enableTemplatesBtns(boolean isEnabled) {
		for(JButton btn:templateBtns) {
			btn.setEnabled(isEnabled);
		}
	}

	public void updateToolbar() {
	}

	public void showSimulatorRun() {
		startStopSimBtn.setIcon(GUIUtil.getImage("start.png"));
		startStopSimBtn.setText("Start");

	}



	
}
