    ## Process this file with automake to produce Makefile.in

icondir = $(datadir)/icons/hicolor/48x48/apps
dist_icon_DATA = mpdevil.png

svgicondir = $(datadir)/icons/hicolor/scalable/apps
dist_svgicon_DATA = mpdevil.svg


gtk_update_icon_cache = gtk-update-icon-cache -f -t $(datadir)/icons/hicolor

install-data-hook: update-icon-cache
uninstall-hook: update-icon-cache
update-icon-cache:  
	@-if test -z "$(datadir)"; then \
		echo "Updating Gtk icon cache."; \
		$(gtk_update_icon_cache); \
	else \
		echo "*** Icon cache not updated.  After (un)install, run this:"; \
		echo "***   $(gtk_update_icon_cache)"; \
	fi

desktop_in_files= mpdevil.desktop.in
desktop_files=$(desktop_in_files:.desktop.in=.desktop)
@INTLTOOL_DESKTOP_RULE@

gsettings_SCHEMAS = org.mpdevil.gschema.xml
@GSETTINGS_RULES@

Applicationsdir = $(datadir)/applications
Applications_DATA = $(desktop_files)

EXTRA_DIST = $(desktop_in_files) $(desktop_files) $(gsettings_SCHEMAS)

DISTCLEANFILES = $(desktop_files)
