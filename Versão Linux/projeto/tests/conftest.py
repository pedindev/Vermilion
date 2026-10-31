from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "testes de campeonato"))


def pytest_addoption(parser):
    parser.addoption("--motor-real", action="store_true")


def pytest_configure(config):
    config.addinivalue_line("markers", "motor_real: consulta o executável local")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--motor-real"):
        for item in items:
            if "motor_real" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Use --motor-real"))
