import json
from importlib.resources import files


def load():
    suite = json.loads(files("ghostframe").joinpath("fixtures.json").read_text())
    for group in ("development", "regression"):
        for fixture in suite[group]:
            fixture["synthetic"] = True
    return suite


def flagship():
    return load()["development"][0]
