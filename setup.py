#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This file is based on https://github.com/kassoulet/soundconverter
import os
import DistUtilsExtra.auto

class Install(DistUtilsExtra.auto.install_auto):
	def run(self):
		DistUtilsExtra.auto.install_auto.run(self)
		# after DistUtilsExtra automatically copied data/org.mpdevil.gschema.xml
		# to /usr/share/glib-2.0/schemas/ it doesn't seem to compile them.
		glib_schema_path = os.path.join(self.install_data, 'share/glib-2.0/schemas/')
		cmd = 'glib-compile-schemas {}'.format(glib_schema_path)
		print('running {}'.format(cmd))
		os.system(cmd)

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
	cmdclass={'install': Install}
)

