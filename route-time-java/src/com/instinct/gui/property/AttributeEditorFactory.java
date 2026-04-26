package com.instinct.gui.property;

import java.util.Collection;

import javax.swing.JComboBox;
import javax.swing.JComponent;
import javax.swing.JTextField;

import com.instinct.service.StaticUtil;

public class AttributeEditorFactory<T> {

	public static AttributeEditor<Integer> buildCombo(String displayName, Integer defaultVal, Collection<Integer> collection) {
		return new ComboAttributeEditor<Integer>(displayName, defaultVal, collection);
	}
	
	public static AttributeEditor<String> buildCombo(String displayName, String defaultVal, String[] collection) {
		return new ComboAttributeEditor<String>(displayName, defaultVal, collection);
	}
	
	
	
	public static AttributeEditor<Integer> buildCombo(String displayName, Integer defaultVal, Integer array[]) {
		
		return new ComboAttributeEditor<Integer>(displayName, defaultVal, array);
	}
	
	public static AttributeEditor<Double> buildCombo(String displayName, Double defaultVal, Double array[]) {
		
		return new ComboAttributeEditor<Double>(displayName, defaultVal, array);
	}
	
	public static AttributeEditor<String> buildText(String displayName,String defaultVal) {
		return new TextAttributeEditor(displayName,defaultVal);
	}
	
	public static AttributeEditor<Double> buildDouble(String displayName,double defaultVal, double max, double min) {
		return new DoubleAttributeEditor(displayName,defaultVal, max, min);
	}	
	
	public static AttributeEditor<Integer> buildInteger(String displayName,int defaultVal, int max, int min) {
		return new IntAttributeEditor(displayName,defaultVal, max, min);
	}	
}

class IntAttributeEditor implements AttributeEditor<Integer> {
	private JTextField textFld;
	private int max, min;
	private String displayName;
	private boolean isEditable;
	IntAttributeEditor(String displayName, int defaultVal, int max, int min) {
		textFld=new JTextField();
		this.displayName=displayName;
		textFld.setText(defaultVal+"");
		this.max=max;
		this.min=min;
	}
	
	@Override
	public JComponent getEditor() {
		return textFld;
	}

	@Override
	public boolean isValid() {
		return getSelection()>=min && getSelection()<=max;
	}

	@Override
	public Integer getSelection() {
		return Integer.valueOf(textFld.getText());
	}

	@Override
	public void setSelection(Integer text) {
		textFld.setText(text.toString());
	}
	
	public String getDisplayName() {
		return displayName;
	}

	@Override
	public void setEditable(boolean b) {
		this.isEditable=b;
		textFld.setEditable(isEditable);
		}

	public boolean isEditable() {
		return isEditable;

	}
}


class DoubleAttributeEditor implements AttributeEditor<Double> {
	private JTextField textFld;
	private double max, min;
	private String displayName;
	private boolean isEditable;
	DoubleAttributeEditor(String displayName, Double defaultVal, Double max, Double min) {
		textFld=new JTextField();
		this.displayName=displayName;
		if(defaultVal!=null) {
			double rounded=StaticUtil.round(defaultVal);
			String value=String.valueOf(rounded);
			textFld.setText(value);
		}
		this.max=max;
		this.min=min;
	}
	
	@Override
	public void setEditable(boolean b) {
		this.isEditable=b;
		textFld.setEditable(isEditable);
	}
	
	public boolean isEditable() {
		return isEditable;
	}
	
	@Override
	public JComponent getEditor() {
		return textFld;
	}

	@Override
	public boolean isValid() {
		return getSelection()>=min && getSelection()<=max;
	}

	@Override
	public Double getSelection() {
		double value= Double.valueOf(textFld.getText());
		return value;
	}

	@Override
	public void setSelection(Double text) {
		textFld.setText(text.toString());
	}
	
	public String getDisplayName() {
		return displayName;
	}
}

class ComboAttributeEditor<T> implements AttributeEditor<T> {
	private JComboBox<T> combo;
	private String displayName;
	private boolean isEditable;
	ComboAttributeEditor(String displayName, T defaultVal, Collection<T> validValues) {
		this.displayName=displayName;
		combo=new JComboBox<T>();	
		for(T t:validValues) {
			combo.addItem(t);
		}
		if(defaultVal!=null) {
			combo.setSelectedItem(defaultVal);
		}
	}
	
	public ComboAttributeEditor(String displayName, T defaultVal, T[] array) {
		this.displayName=displayName;
		combo=new JComboBox<T>();	
		for(T t:array) {
			combo.addItem(t);
		}
		if(defaultVal!=null) {
			combo.setSelectedItem(defaultVal);
		}	}

	@Override
	public void setEditable(boolean b) {
		this.isEditable=b;
		combo.setEditable(isEditable);
	}
	
	public boolean isEditable() {
		return isEditable;
	}
	
	@Override
	public JComponent getEditor() {
		return combo;
	}

	@Override
	public boolean isValid() {
		return true;
	}

	@Override
	public T getSelection() {
		return (T)combo.getSelectedItem();
	}

	@Override
	public void setSelection(T t) {
		combo.setSelectedItem(t);
	}
	
	public String getDisplayName() {
		return displayName;
	}
}

class TextAttributeEditor implements AttributeEditor<String> {
	private JTextField textFld;
	private String displayName;
	private boolean isEditable;
	TextAttributeEditor(String displayName,String defaultVal) {
		textFld=new JTextField();	
		this.displayName=displayName;
		if(defaultVal!=null) {
			textFld.setText(defaultVal);
		}
	}
	
	@Override
	public JComponent getEditor() {
		return textFld;
	}

	@Override
	public boolean isValid() {
		return true;
	}

	@Override
	public String getSelection() {
		return textFld.getText();
	}

	@Override
	public void setSelection(String text) {
		textFld.setText(text);
	}
	
	public String getDisplayName() {
		return displayName;
	}
	
	@Override
	public void setEditable(boolean b) {
		this.isEditable=b;
		textFld.setEditable(isEditable);
	}

	public boolean isEditable() {
		return isEditable;
	}
	
	
	public String toString() {
		return textFld.getText();
	}

	@Override
	public int hashCode() {
		final int prime = 31;
		int result = 1;
		result = prime * result + ((displayName == null) ? 0 : displayName.hashCode());
		return result;
	}

	@Override
	public boolean equals(Object obj) {
		if (this == obj)
			return true;
		if (obj == null)
			return false;
		if (getClass() != obj.getClass())
			return false;
		TextAttributeEditor other = (TextAttributeEditor) obj;
		if (displayName == null) {
			if (other.displayName != null)
				return false;
		} else if (!displayName.equals(other.displayName))
			return false;
		return true;
	}

}