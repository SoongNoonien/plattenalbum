i18n.merge_file(
        input: 'fr.chartrandphilippe.Vinyle.desktop.in',
       output: 'fr.chartrandphilippe.Vinyle.desktop',
         type: 'desktop',
       po_dir: '../po',
      install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

metainfo_file = i18n.merge_file(
        input: 'fr.chartrandphilippe.Vinyle.metainfo.xml.in',
       output: 'fr.chartrandphilippe.Vinyle.metainfo.xml',
       po_dir: '../po',
      install: true,
  install_dir: join_paths(get_option('datadir'), 'metainfo')
)

gnome.compile_resources(
  'fr.chartrandphilippe.Vinyle', 'fr.chartrandphilippe.Vinyle.gresource.xml',
  gresource_bundle: true,
        source_dir: '.',
       install_dir: resources_dir,
           install: true,
      dependencies: metainfo_file
)

install_data('fr.chartrandphilippe.Vinyle.gschema.xml', install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas'))

install_data('fr.chartrandphilippe.Vinyle.svg', install_dir: join_paths(get_option('datadir'), 'icons/hicolor/scalable/apps'))
install_data('fr.chartrandphilippe.Vinyle-symbolic.svg', install_dir: join_paths(get_option('datadir'), 'icons/hicolor/symbolic/apps'))
