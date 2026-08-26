import os
import yaml

_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yml")
_config = None


def load_config():
    global _config
    if _config is None:
        config_path = os.environ.get("COPY_DAY_UPDATE_CONFIG", _DEFAULT_CONFIG_PATH)
        with open(config_path, "r") as f:
            _config = yaml.safe_load(f)
    return _config
