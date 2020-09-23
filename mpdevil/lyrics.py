#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# mpdevil - MPD Client.
# Copyright 2020 Martin Wagner <martin.wagner.dev@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
# USA

import requests
from bs4 import BeautifulSoup, Comment

class LyricsHelper(object):
	def __init__(self, debug=False):
		self._debug=debug

	def _debug_print(self, text):
		if self._debug:
			print(text)

	def _get_lyrics_lyriki(self, singer, song):
		self._debug_print("lyriki")
		replaces=((' ', '_'),('.', '_'),('@', '_'),(',', '_'),(';', '_'),('&', '_'),('\\', '_'),('/', '_'),('"', '_'))
		for char1, char2 in replaces:
			singer=singer.replace(char1, char2)
			song=song.replace(char1, char2)
		self._debug_print('http://www.lyriki.com/{0}:{1}'.format(singer,song))
		r=requests.get('http://www.lyriki.com/{0}:{1}'.format(singer,song))
		s=BeautifulSoup(r.text)
		lyrics=s.p
		if lyrics is None:
			raise ValueError("Not found")
		elif str(lyrics).startswith("<p>There is currently no text in this page."):
			raise ValueError("Not found")
		try:
			lyrics.tt.unwrap()
		except:
			pass
		output=str(lyrics)[3:-4].replace('\n','').replace('<br/>','\n')
		return output

	def _get_lyrics_songlyrics(self, singer, song):
		self._debug_print("songlyrics")
		replaces=((' ', '-'),('.', '-'),('_', '-'),('@', '-'),(',', '-'),(';', '-'),('&', '-'),('\\', '-'),('/', '-'),('"', '-'))
		for char1, char2 in replaces:
			singer=singer.replace(char1, char2)
			song=song.replace(char1, char2)
		self._debug_print('https://www.songlyrics.com/{0}/{1}-lyrics/'.format(singer,song))
		r=requests.get('https://www.songlyrics.com/{0}/{1}-lyrics/'.format(singer,song))
		s=BeautifulSoup(r.text)
		lyrics=s.find(id="songLyricsDiv")
		if lyrics is None:
			raise ValueError("Not found")
		elif str(lyrics)[58:-4].startswith("Sorry, we have no"):
			raise ValueError("Not found")
		try:
			lyrics.i.unwrap()
		except:
			pass
		output=str(lyrics)[58:-4].replace('\n','').replace('\r','').replace(' /', '').replace('<br/>','\n')
		return output

	def _get_lyrics_letras(self, singer, song):
		self._debug_print("letras")
		replaces=((' ', '+'),('.', '_'),('@', '_'),(',', '_'),(';', '_'),('&', '_'),('\\', '_'),('/', '_'),('"', '_'),('(', '_'),(')', '_'))
		for char1, char2 in replaces:
			singer=singer.replace(char1, char2)
			song=song.replace(char1, char2)
		self._debug_print('https://www.letras.mus.br/winamp.php?musica={1}&artista={0}'.format(singer,song))
		r=requests.get('https://www.letras.mus.br/winamp.php?musica={1}&artista={0}'.format(singer,song))
		s=BeautifulSoup(r.text)
		s=s.find(id="letra-cnt")
		if s is None:
			raise ValueError("Not found")
		pragraphs=[i for i in s.children][2:-1]  # remove unneded pragraphs
		lyrics=""
		for p in pragraphs:
			for line in p.stripped_strings:
				lyrics+=line+'\n'
			lyrics+='\n'
		output=lyrics[:-2]  # omit last two newlines
		if output != "":  # assume song is instrumental when lyrics are empty
			return output
		else:
			return "Instrumental"

	def get_lyrics(self, singer, song):
		self._debug_print("fetching lyrics for '"+singer+"' - '"+song+"'")
		providers=[self._get_lyrics_letras, self._get_lyrics_lyriki, self._get_lyrics_songlyrics]
		text=None
		for provider in providers:
			try:
				text=provider(singer, song)
				break
			except ValueError:
				pass
		return text

