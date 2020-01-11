README for mpdevil
==================
mpdevil is focused on playing your local music directly instead of managing playlists or playing network streams. So it neither supports saving playlists nor restoring them. Therefore mpdevil is mainly a music browser which aims to be easy to use. mpdevil dosen't store any client side database of your music library. Instead all tags and covers get presented to you in real time. So you'll never see any outdated information in your browser.

Features
--------

-playing songs without doubleclicking

-displaying covers

-fetching lyrics form the web (based on PyLyrics 1.1.0)

-searching songs in your music library

-removing single tracks form playlist by hovering and pressing del

-sending notifications on title change

-managing multiple mpd servers

Building and installation
-------------------------

To build from the latest source, use::

    ./autogen.sh
    make
    make install
    
