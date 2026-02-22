#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Vinyle - MPD Client.
# Copyright (C) 2020-2026 Martin Wagner <martin.wagner.dev@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GLib

import sys
import signal
import locale
from gettext import textdomain, bindtextdomain

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error as e:
    print(e)
locale.bindtextdomain("fr.chartrandphilippe.Vinyle", "@LOCALE_DIR@")
locale.textdomain("fr.chartrandphilippe.Vinyle")
bindtextdomain("fr.chartrandphilippe.Vinyle", localedir="@LOCALE_DIR@")
textdomain("fr.chartrandphilippe.Vinyle")
Gio.Resource._register(Gio.resource_load(GLib.build_filenamev(["@RESOURCES_DIR@", "fr.chartrandphilippe.Vinyle.gresource"])))


from vinylelib.application import Vinyle

if __name__ == "__main__":
    app=Vinyle()
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
    app.run(sys.argv)

