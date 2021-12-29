project('mpdevil',
          version: '1.4.1',
    meson_version: '>= 0.47.0',
)

i18n = import('i18n')
gnome = import('gnome')

resources_dir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())

subdir('data')
subdir('src')
subdir('po')
