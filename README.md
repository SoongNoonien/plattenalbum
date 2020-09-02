README for mpdevil
==================
mpdevil is focused on playing your local music directly instead of managing playlists or playing network streams. So it neither supports saving playlists nor restoring them. Therefore mpdevil is mainly a music browser which aims to be easy to use. mpdevil dosen't store any client side database of your music library. Instead all tags and covers get presented to you in real time. So you'll never see any outdated information in your browser. mpdevil strongly relies on tags.

![ScreenShot](screenshots/mainwindow_0.8.5.png)

Features
--------

- play songs without doubleclicking
- search songs in your music library
- manage multiple mpd servers
- filter by genre
- control with media keys
- displays covers
- sends notifications on title change
- fetches lyrics from the web (based on PyLyrics)
- MPRIS interface (based on mpDris2)

See: https://github.com/SoongNoonien/mpdevil/wiki/Usage
    
Package Installation
--------------------

See:
https://github.com/SoongNoonien/mpdevil/releases/latest
    
Ubuntu, Debian, Mint:
- Download the .deb file
- Open a console
- Navigate into download dir
- Run: `sudo apt install ./mpdevil_VERSION.deb`

Arch, Manjaro (see: https://aur.archlinux.org/packages/mpdevil/):
- Download the PKGBUILD from the AUR
- Open a console
- Navigate into download dir
- Run: `makepkg -sirc`
- Alternatively install it with an AUR helper

Gentoo (see: https://wiki.gentoo.org/wiki/Custom_repository):
- Download the .ebuild
- Place it into your local tree
- Generate manifest file
- Run: `emerge mpdevil`

Building
--------

Build dependencies:
- DistUtilsExtra

Dependencies:
- Gtk3
- Python3

Python modules:
- mpd (python-mpd2)
- gi (Gtk, Gio, Gdk, GdkPixbuf, Pango, GObject, GLib, Notify)
- requests
- bs4 (beautifulsoup)
- dbus
- pkg_resources (setuptools)

Run:
```bash
git clone https://github.com/SoongNoonien/mpdevil.git
cd mpdevil
sudo python3 setup.py install
sudo glib-compile-schemas /usr/share/glib-2.0/schemas
sudo gtk-update-icon-cache
sudo update-desktop-database
```

Translation
-----------

mpdevil is currently available in English and German. If you speek another language you can easily translate mpdevil by using `poedit`. Just import `po/mpdevil.pot` from this repo into `poedit`. To test your translation copy the new `.po` file in your cloned mpdevil repo into the `po` directory and proceed as described in the Building section. To integrate your translation into mpdevil just send me an e-mail or create a pull request. Link to `poedit`: https://poedit.net/

