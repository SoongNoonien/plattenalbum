bin_SCRIPTS = \
	mpdevil

EXTRA_DIST = mpdevil.py
CLEANFILES = $(bin_SCRIPTS)

mpdevil: mpdevil.py
	sed -e s!\@datadir\@!$(datadir)!  -e s!\@libdir\@!$(libdir)!  -e s!\@version\@!$(VERSION)! < $< > $@
	chmod +x $@


