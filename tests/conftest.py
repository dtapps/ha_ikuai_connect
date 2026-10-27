"""pytest 全局夹具（pytest-homeassistant-custom-component）。

测试策略：
- HA 的接线（入口、平台、配置流、服务）跑在真实 Home Assistant 上；
- 只把 `IkuaiAPI` 的网络方法换成替身 —— HTTP 细节由 test_api.py 用假会话单独覆盖，
  这样这里失败就一定是「集成逻辑错了」，不是「网络抖动」。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ikuai_connect import api as api_module_ref
from custom_components.ikuai_connect.api import IkuaiAPI
from custom_components.ikuai_connect.const import (
    CONF_OFFLINE_GRACE_PERIOD,
    CONF_TRACKER_CONFIG,
    DOMAIN,
)
from custom_components.ikuai_connect.coordinator import IkuaiCoordinator
from tests import payloads
from tests.doubles import FakeSession

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """让 HA 扫描仓库根目录的 custom_components（否则找不到本集成）。"""
    yield


@pytest.fixture
def results() -> list:
    """一轮完整的路由器快照（17 个槽位，可被用例就地修改）。"""
    return payloads.build_results()


@pytest.fixture
def tracker_options() -> dict:
    """默认追踪一台在线终端，让 device_tracker 平台真正建出实体。"""
    return {
        CONF_TRACKER_CONFIG: {payloads.MAC1: {"name": "小米 Pad", "buffer": 5}},
        CONF_OFFLINE_GRACE_PERIOD: 1,
    }


@pytest.fixture
def config_entry(hass, tracker_options) -> MockConfigEntry:
    """已注册到 hass 的配置条目（还没 setup）。"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="iKuai Connect",
        data={
            CONF_HOST: payloads.HOST,
            CONF_TOKEN: "test-token",
            CONF_TRACKER_CONFIG: {},
        },
        options={CONF_SCAN_INTERVAL: 30, **tracker_options},
        entry_id="ikuai_test_entry",
        unique_id=payloads.HOST.lower(),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def api_stub(monkeypatch, results) -> SimpleNamespace:
    """把 IkuaiAPI 的网络方法替换成可断言的 AsyncMock。"""
    stubs: dict[str, AsyncMock] = {}

    def _patch(name: str, **kwargs) -> AsyncMock:
        mock = AsyncMock(**kwargs)
        monkeypatch.setattr(IkuaiAPI, name, mock)
        stubs[name] = mock
        return mock

    # 协调器入口：整轮数据一把给
    _patch("get_all_data", return_value=results)
    # 单点查询
    _patch("get_system_info", return_value=results[0])
    _patch("get_lan_devices", return_value=results[1])
    # 服务层数据源
    _patch("get_client_traffic_summary", return_value=payloads.traffic_summary())
    _patch("get_client_protocol_stats", return_value=payloads.protocol_stats())
    _patch("get_offline_history", return_value=payloads.offline_history())
    # 动作类：返回 True 即可，断言看调用参数
    for action in (
        "trigger_backup",
        "check_upgrade",
        "start_upgrade",
        "trigger_immediate_reboot",
        "set_mac_mode",
        "toggle_mac_rule",
        "add_mac_rule",
        "delete_mac_rule",
    ):
        _patch(action, return_value=True)
    _patch("call_custom_api", return_value={"success": True, "data": {}})

    return SimpleNamespace(
        **stubs,
        get=lambda name: stubs[name],
        results=results,
        fail=lambda name, error: setattr(stubs[name], "side_effect", error),
    )


@pytest.fixture
async def setup_integration(hass, config_entry, api_stub):
    """把条目跑完 setup，断言失败直接抛出。"""

    async def _setup():
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        return config_entry

    return _setup


# ---------------------------------------------------------------- 非 HA 层夹具


@pytest.fixture
def api_module():
    """api 模块本体，供 HTTP 层单元测试直接操作。"""
    return api_module_ref


@pytest.fixture
def make_api(monkeypatch):
    """构造 IkuaiAPI，并把客户端会话换成 FakeSession。"""

    def _factory(session=None, host="https://10.0.0.1", token="test-token"):
        session = session or FakeSession()
        monkeypatch.setattr(
            api_module_ref, "async_get_clientsession", lambda hass: session
        )
        return api_module_ref.IkuaiAPI(hass=object(), host=host, token=token), session

    return _factory


@pytest.fixture
def make_coordinator(hass):
    """构造协调器；api 只需暴露 get_all_data()。"""

    def _factory(results, options=None, host=payloads.HOST, error=None):
        class StubAPI:
            async def get_all_data(self, include_clients: bool = True):
                if error is not None:
                    raise error
                return results

        coordinator = IkuaiCoordinator(hass, StubAPI(), host, 15)
        coordinator.config_entry = SimpleNamespace(
            options=options or {}, title="测试路由", entry_id="entry_test"
        )
        return coordinator

    return _factory


def find_entity_id(hass, domain: str, unique_id: str) -> str:
    """按 unique_id 反查 entity_id（避开翻译/命名带来的不确定性）。"""
    from homeassistant.helpers import entity_registry as er

    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, f"找不到 unique_id={unique_id} 的 {domain} 实体"
    return entity_id


def state_of(hass, domain: str, unique_id: str) -> Any:
    """取实体状态。"""
    return hass.states.get(find_entity_id(hass, domain, unique_id))
