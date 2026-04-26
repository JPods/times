package com.instinct.objects.network;

import javax.swing.JPopupMenu;

import com.instinct.gui.pad.widgets.Drawable;

/**
 * Created by user on 27-07-2014.
 */
public interface RenderableObject<T> {

     Drawable<T> getUI();
     
    JPopupMenu getPopupMenu();
}
