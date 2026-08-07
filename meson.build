project('plattenalbum', version: '2.6.0')

python = import('python')
i18n = import('i18n')
gnome = import('gnome')

resources_dir = get_option('prefix')/get_option('datadir')/'de.wagnermartin.Plattenalbum'

subdir('data')
subdir('src')
subdir('po')

gnome.post_install(glib_compile_schemas: true, gtk_update_icon_cache: true, update_desktop_database: true)
