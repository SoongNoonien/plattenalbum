i18n.merge_file(
        input: 'de.wagnermartin.Plattenalbum.desktop.in',
       output: 'de.wagnermartin.Plattenalbum.desktop',
         type: 'desktop',
       po_dir: '../po',
      install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

gnome.compile_resources(
  'de.wagnermartin.Plattenalbum', 'de.wagnermartin.Plattenalbum.gresource.xml',
  gresource_bundle: true,
        source_dir: '.',
       install_dir: resources_dir,
           install: true
)

install_data('de.wagnermartin.Plattenalbum.appdata.xml', install_dir: join_paths(get_option('datadir'), 'metainfo'))
install_data('de.wagnermartin.Plattenalbum.gschema.xml', install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas'))

install_data('de.wagnermartin.Plattenalbum.svg', install_dir: join_paths(get_option('datadir'), 'icons/hicolor/scalable/apps'))
install_data('de.wagnermartin.Plattenalbum-symbolic.svg', install_dir: join_paths(get_option('datadir'), 'icons/hicolor/symbolic/apps'))
