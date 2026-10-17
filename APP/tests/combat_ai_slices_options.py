"""Parse opt-in overrides for the combat AI batch and two stock replay wrappers."""


def opt_in_options(config):
    """No pytest ``-o`` arguments means no opt-in, including pytest's None default."""
    return dict(value.split('=', 1)
                for value in (config.getoption('override_ini') or ())
                if '=' in value)
