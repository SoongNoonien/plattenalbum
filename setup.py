#!/usr/bin/python3
# -*- coding: utf-8 -*-

import DistUtilsExtra.auto

DistUtilsExtra.auto.setup(
	name='mpdevil',
	version='0.8.5',
	author="Martin Wagner",
	author_email="martin.wagner.dev@gmail.com",
	description=('A small MPD client written in python'),
	url="https://github.com/SoongNoonien/mpdevil",
	license='GPL-3.0',
	data_files=[
		('share/icons/hicolor/48x48/apps/', ['data/mpdevil.png']),
		('share/icons/hicolor/scalable/apps/', ['data/mpdevil.svg'])
	],
)

