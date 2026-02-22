project('vinyle', version: '2.5.0')

i18n = import('i18n')
gnome = import('gnome')

resources_dir = join_paths(get_option('prefix'), get_option('datadir'), 'fr.chartrandphilippe.Vinyle')

subdir('src/vinylelib')
subdir('data')
subdir('src')
subdir('po')

gnome.post_install(glib_compile_schemas: true, gtk_update_icon_cache: true, update_desktop_database: true)
