conf = configuration_data()
conf.set('RESOURCES_DIR', resources_dir)
conf.set('LOCALE_DIR', join_paths(get_option('prefix'), get_option('datadir'), 'locale'))

configure_file(
          input: 'mpdevil.py',
         output: 'mpdevil',
  configuration: conf,
    install_dir: join_paths(get_option('prefix'), get_option('bindir'))
)
