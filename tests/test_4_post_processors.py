import sys
import os
import pytest

sys.path.append(os.path.abspath('../elara'))
from elara import postprocessing
from elara.config import Config, PathFinderWorkStation
from elara.inputs import InputsWorkStation
from elara.event_handlers import EventHandlerWorkStation
from elara.plan_handlers import PlanHandlerWorkStation
sys.path.append(os.path.abspath('../tests'))


def test_generate_period_headers():
    hours = 24
    headers = postprocessing.generate_period_headers(hours)
    assert isinstance(headers, list)
    assert len(headers) == hours
    assert all(isinstance(elem, str) for elem in headers)


# Config
@pytest.fixture
def test_config():
    config_path = os.path.join('tests/test_xml_scenario.toml')
    config = Config(config_path)
    assert config
    return config


# Paths
@pytest.fixture
def test_paths(test_config):
    paths = PathFinderWorkStation(test_config)
    paths.connect(managers=None, suppliers=None)
    paths.load_all_tools()
    paths.build()
    assert set(paths.resources) == set(paths.tools)
    return paths


# Input Manager
@pytest.fixture
def input_manager(test_config, test_paths):
    input_workstation = InputsWorkStation(test_config)
    input_workstation.connect(managers=None, suppliers=[test_paths])
    input_workstation.load_all_tools()
    input_workstation.build()
    return input_workstation


@pytest.fixture
def vkt_post_processor(test_config):
    return postprocessing.VKT(test_config, 'car')


def test_vkt_prerequisites(vkt_post_processor):
    assert vkt_post_processor.check_prerequisites()


def test_vkt_build(vkt_post_processor, ):
    vkt_post_processor.build(None)


def test_post_process_workstation(test_config, test_paths):
    input_workstation = InputsWorkStation(test_config)
    input_workstation.connect(managers=None, suppliers=[test_paths])
    input_workstation.load_all_tools()
    input_workstation.build()

    event_workstation = EventHandlerWorkStation(test_config)
    event_workstation.connect(managers=None, suppliers=[input_workstation])
    event_workstation.load_all_tools(option='bus')
    event_workstation.build()

    plan_workstation = PlanHandlerWorkStation(test_config)
    plan_workstation.connect(managers=None, suppliers=[input_workstation])
    tool = plan_workstation.tools['mode_share']
    plan_workstation.resources['mode_share'] = tool(test_config, 'all')
    plan_workstation.build()

    pp_workstation = postprocessing.PostProcessWorkStation(test_config)
    pp_workstation.connect(managers=None, suppliers=[event_workstation, plan_workstation])
    tool = pp_workstation.tools['vkt']
    pp_workstation.resources['vkt'] = tool(test_config, 'bus')
    pp_workstation.build()




