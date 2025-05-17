import os


def get_assets(path: str):
    cur_dir = os.path.dirname(__file__)
    return os.path.join(cur_dir, "../assets/", path)
