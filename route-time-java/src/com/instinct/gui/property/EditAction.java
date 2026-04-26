package com.instinct.gui.property;

import java.util.Map;

public interface EditAction {

	public void doEdit(Map<String, AttributeEditor<?>> editors);

	public void doEditMultiple(Map<String,Map<String, AttributeEditor<?>>> editors);

}
