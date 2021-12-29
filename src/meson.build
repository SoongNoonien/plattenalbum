conf = configuration_data()
conf.set('RESOURCES_DIR', resources_dir)

configure_file(
          input: 'mpdevil.in',
         output: 'mpdevil',
  configuration: conf,
    install_dir: join_paths(get_option('prefix'), get_option('bindir'))
)
