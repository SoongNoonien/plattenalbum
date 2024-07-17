Plattenalbum
============
A client for the Music Player Daemon (MPD).

Browse your collection while viewing large album covers. Play your music without managing playlists.</p>

![ScreenShot](screenshots/main_window.png)

Package Installation
--------------------

Flatpak:

<a href='https://flathub.org/apps/details/de.wagnermartin.Plattenalbum'><img width='240' alt='Download on Flathub' src='https://flathub.org/assets/badges/flathub-badge-en.png'/></a>

Arch:
- https://aur.archlinux.org/packages/plattenalbum
- https://aur.archlinux.org/packages/plattenalbum-git

Gentoo (see: https://wiki.gentoo.org/wiki/Custom_repository):
- Download the .ebuild (https://github.com/SoongNoonien/plattenalbum/releases/latest)
- Place it into your local tree
- Generate manifest file
- Run: `emerge plattenalbum`

Building
--------

Build dependencies:
- meson
- gettext
- glib2 (Ubuntu/Debian: libglib2.0-dev-bin, libglib2.0-bin)

Dependencies:
- GTK4 >=4.12.0
- libadwaita >=1.5.0
- Python3

Python modules:
- mpd (python-mpd2 >=3.1)
- gi (Gtk, Adw, Gio, Gdk, Pango, GObject, GLib)

Run:
```bash
git clone https://github.com/SoongNoonien/plattenalbum.git
cd plattenalbum
meson setup builddir --prefix=/usr/local
sudo ninja -C builddir install
```

Translation
-----------

This program is currently available in English, German, Dutch, Bulgarian, Turkish, Polish, French, Japanese, Hindi, Russian and Brazilian Portuguese. If you speak one of these or even another language, you can easily translate it by using [poedit](https://poedit.net). Just import `po/de.wagnermartin.Plattenalbum.pot` from this repo into `poedit`. To test your translation, copy the new `.po` file into the `po` directory of your cloned plattenalbum repo and proceed as described in the [Building](#building) section. To get your translation merged, just send me an e-mail or create a pull request.
