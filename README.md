README for mpdevil
==================
Mpdevil is a simple music browser for the Music Player Daemon (MPD) which is focused on playing local music without the need of managing playlists. Instead of maintaining a client side database of your music library, mpdevil loads all tags and covers on demand. So you'll never see any outdated information in the browser. Mpdevil strongly relies on tags.

![ScreenShot](screenshots/mainwindow_1.11.0.png)

Features
--------

- Display large covers
- Play songs without double click
- Lyrics from: https://www.letras.mus.br
- MPRIS interface (based on mpDris2)
- Basic queue manipulation (move and delete single tracks)

See: https://github.com/SoongNoonien/mpdevil/wiki/Usage

Package Installation
--------------------

See:
https://github.com/SoongNoonien/mpdevil/releases/latest

Ubuntu, Debian, Mint, Raspberry Pi OS:
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

Flatpak:

<a href='https://flathub.org/apps/details/org.mpdevil.mpdevil'><img width='240' alt='Download on Flathub' src='https://flathub.org/assets/badges/flathub-badge-en.png'/></a>

Building
--------

Build dependencies:
- meson
- gettext
- glib2 (Ubuntu/Debian: libglib2.0-dev-bin, libglib2.0-bin)

Dependencies:
- GTK4 >=4.12.0
- libadwaita >=1.4.0
- Python3

Python modules:
- mpd (python-mpd2 >=1.1)
- gi (Gtk, Adw, Gio, Gdk, Pango, GObject, GLib)

Run:
```bash
git clone https://github.com/SoongNoonien/mpdevil.git
cd mpdevil
meson setup builddir --prefix=/usr/local
sudo ninja -C builddir install
sudo glib-compile-schemas /usr/local/share/glib-2.0/schemas
sudo gtk-update-icon-cache
sudo update-desktop-database
```

Translation
-----------

This program is currently available in English, German, Dutch, Bulgarian, Turkish, Polish and French. If you speak one of these or even another language, you can easily translate it by using [poedit](https://poedit.net). Just import `po/mpdevil.pot` from this repo into `poedit`. To test your translation, copy the new `.po` file into the `po` directory of your cloned mpdevil repo and proceed as described in the [Building](#building) section. To get your translation merged, just send me an e-mail or create a pull request.
