conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('LOCALE_DIR', get_option('prefix')/get_option('datadir')/'locale')
conf.set('RESOURCES_DIR', resources_dir)

configure_file(
          input: 'plattenalbum.py',
         output: 'plattenalbum',
  configuration: conf,
    install_dir: get_option('prefix')/get_option('bindir')
)
