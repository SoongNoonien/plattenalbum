i18n.merge_file(
        input: 'org.mpdevil.mpdevil.desktop.in',
       output: 'org.mpdevil.mpdevil.desktop',
         type: 'desktop',
       po_dir: '../po',
      install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

gnome.compile_resources(
  'mpdevil', 'mpdevil.gresource.xml',
  gresource_bundle: true,
        source_dir: '.',
       install_dir: resources_dir,
           install: true
)

install_data('org.mpdevil.mpdevil.appdata.xml', install_dir: join_paths(get_option('datadir'), 'metainfo'))
install_data('org.mpdevil.mpdevil.gschema.xml', install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas'))

install_subdir('icons', install_dir: get_option('datadir'))
