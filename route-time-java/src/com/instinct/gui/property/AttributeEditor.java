package com.instinct.gui.property;

import javax.swing.JComponent;

public interface AttributeEditor<T> {

	public JComponent getEditor();
	
	public boolean isValid();
	
	public T getSelection();
	
	public void setSelection(T t);
	
	public String getDisplayName();

	public void setEditable(boolean b);
	
	public boolean isEditable();
	
}
