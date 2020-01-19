dnl -*- Mode: autoconf -*-
dnl Process this file with autoconf to produce a configure script.
AC_PREREQ([2.68])
AC_INIT([mpdevil], [0.4.2])
AC_CONFIG_SRCDIR([bin/mpdevil.py])
AM_INIT_AUTOMAKE
AC_CONFIG_MACRO_DIR([m4])

m4_define(required_python_abi, [3.0])
m4_define(required_python_version, [3.0])
m4_define(required_gtk_version, [3.0])

dnl put the ACLOCAL flags in the makefile
ACLOCAL="$ACLOCAL $ACLOCAL_FLAGS"

#ALL_LINGUAS="ar ast bg br ca cs da de el en_AU en_CA en_GB eo es et eu fa fi fr_CA fr_FR fr gl he hi hu it ja ko lt lv ml ms nb nl pl pt_BR pt ru sk sl sq sr@latin sr@Latn sr sv te tr uk vi zh_CN zh_TW"
ALL_LINGUAS="de"

GETTEXT_PACKAGE="mpdevil"
AC_SUBST([GETTEXT_PACKAGE])
AC_DEFINE_UNQUOTED([GETTEXT_PACKAGE], "$GETTEXT_PACKAGE", [Gettext package])
AM_GLIB_GNU_GETTEXT
IT_PROG_INTLTOOL
GLIB_GSETTINGS

AM_PATH_PYTHON(required_python_version)


dnl Check for correctly installed gtk
AC_MSG_CHECKING(for gtk required_gtk_version installed)
prog="
import gi
gi.require_version('Gtk', 'required_gtk_version')
from gi.repository import Gtk
assert Gtk._version
"
if $PYTHON -c "$prog" 1>&AS_MESSAGE_LOG_FD 2>&AS_MESSAGE_LOG_FD; then
    AC_MSG_RESULT(found)
else
    AC_MSG_RESULT(not found)
    AC_MSG_ERROR(required gtk version not found)
fi

dnl Check for MPDClient
AC_MSG_CHECKING(for MPDClient installed)
prog="
from mpd import MPDClient
"
if $PYTHON -c "$prog" 1>&AS_MESSAGE_LOG_FD 2>&AS_MESSAGE_LOG_FD; then
    AC_MSG_RESULT(found)
else
    AC_MSG_RESULT(not found)
    AC_MSG_ERROR(python module mpd not found)
fi

dnl Check for beautifulsoup
AC_MSG_CHECKING(for beautifulsoup installed)
prog="
from bs4 import BeautifulSoup, Comment
"
if $PYTHON -c "$prog" 1>&AS_MESSAGE_LOG_FD 2>&AS_MESSAGE_LOG_FD; then
    AC_MSG_RESULT(found)
else
    AC_MSG_RESULT(not found)
    AC_MSG_ERROR(python module bs4 not found)
fi

dnl Check for requests
AC_MSG_CHECKING(for requests installed)
prog="
import requests
"
if $PYTHON -c "$prog" 1>&AS_MESSAGE_LOG_FD 2>&AS_MESSAGE_LOG_FD; then
    AC_MSG_RESULT(found)
else
    AC_MSG_RESULT(not found)
    AC_MSG_ERROR(python module requests not found)
fi

AC_CONFIG_FILES([Makefile
        po/Makefile.in
        bin/Makefile
        data/Makefile
        data/mpdevil.desktop.in
        ])
AC_OUTPUT
