"""coordinator 数据清洗流水线测试。

协调器的 `_async_update_data` 本质是纯函数：
输入 = api.get_all_data() 的 17 个槽位 + config_entry.options + 上一轮 data，
输出 = 各平台直接消费的字典。这里逐块钉住它。
"""

from __future__ import annotations

import time

import pytest

from custom_components.ikuai_connect import coordinator as coordinator_module
from custom_components.ikuai_connect.const import (
    CONF_OFFLINE_GRACE_PERIOD,
    CONF_TRACKER_CONFIG,
)
from tests.payloads import (
    HOST,
    MAC1,
    MAC2,
    MAC3,
    MAC4,
    NEVER_SEEN,
    build_results,
    system_slot,
)


def all_tracked_options() -> dict:
    return {
        CONF_TRACKER_CONFIG: {MAC1: {}, MAC2: {}, MAC3: {}, MAC4: {}},
        CONF_OFFLINE_GRACE_PERIOD: 1,
    }


async def run_once(make_coordinator, results=None, options=None):
    results = results if results is not None else build_results()
    coordinator = make_coordinator(results, options=options or all_tracked_options())
    data = await coordinator._async_update_data()
    coordinator.data = data
    return coordinator, data


# ------------------------------------------------------------------ 单位换算


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("abc", None), (0, 0.0), (1024, 1.0), ("2048", 2.0), (1536, 1.5)],
)
def test_kb_to_mb(value, expected):
    assert coordinator_module._kb_to_mb(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("x", None), (0, 0.0), (1_500_000_000, 1.5)],
)
def test_bytes_to_gb(value, expected):
    assert coordinator_module._bytes_to_gb(value) == expected


# ------------------------------------------------------------------ 主设备


@pytest.mark.asyncio
async def test_system_metrics_normalized(make_coordinator):
    _, data = await run_once(make_coordinator)
    system = data["system"]

    assert system["cpu_load"] == 12.0
    assert system["memory_usage"] == 45.0
    assert system["memory_detail"]["total"] == 8192.0  # KB → MB
    assert system["memory_detail"]["buffers"] == 64.0
    assert system["uptime"] == 3725
    assert system["temperature"] == 45.0  # 取第一颗核心
    assert system["ver_string"] == "4.0.307-beta x64 Build202608051709"
    assert system["online_users"] == 7
    assert system["online_user_detail"]["count_5g"] == 3
    assert system["connection_count"] == 300
    assert system["connect_detail"] == {"tcp": 200, "udp": 90, "icmp": 10, "ipv6": 12}
    assert system["upload"] == 1024
    assert system["total_down"] == 2 * 10**9


@pytest.mark.asyncio
async def test_v6_traffic_converted_to_mb_and_gb(make_coordinator):
    _, data = await run_once(make_coordinator)
    v6 = data["system"]["v6_stats"]

    assert v6["upload_speed_v6"] == 1.0  # B/s → KB → MB
    assert v6["download_speed_v6"] == 2.0
    assert v6["total_upload_v6"] == 5.0  # Bytes → GB
    assert v6["total_download_v6"] == 6.0


@pytest.mark.asyncio
async def test_wan_ip_aggregates_only_online_lines(make_coordinator):
    _, data = await run_once(make_coordinator)

    # adsl1 的 ip 是 "--" 且 result=fail，不能混进 WAN IPv4
    assert data["system"]["wan_ip_v4"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_wan_ip_falls_back_to_disconnected(make_coordinator):
    results = build_results()
    results[5] = {
        "iface_check": [{"interface": "adsl0", "ip_addr": "1.2.3.4", "result": "fail"}],
        "iface_stream": [],
    }
    _, data = await run_once(make_coordinator, results)

    assert data["system"]["wan_ip_v4"] == "Disconnected"


@pytest.mark.asyncio
async def test_wireless_detail_fields(make_coordinator):
    _, data = await run_once(make_coordinator)
    wireless = data["system"]["wireless_detail"]

    assert data["system"]["ap_online"] == 2
    assert wireless["total_ap"] == 3
    assert wireless["offline_ap"] == 1
    assert wireless["clients_5g"] == 3
    assert wireless["signal_coverage"] == "96%"
    assert wireless["network_delay"] == "8ms"
    assert wireless["packet_loss"] == "0.5%"
    assert wireless["airtime_health_score"] == 88


# ------------------------------------------------------------------ 终端映射


@pytest.mark.asyncio
async def test_client_name_fallback_chain(make_coordinator):
    _, data = await run_once(make_coordinator)
    clients = data["clients"]

    assert clients[MAC1]["display_name"] == "小米 Pad"
    assert clients[MAC2]["display_name"] == "iPhone 15"
    assert clients[MAC3]["display_name"] == "电视盒子"
    assert clients[MAC4]["display_name"] == "Client ee04"
    # 无 mac 的条目被丢弃
    assert len(clients) == 4


@pytest.mark.asyncio
async def test_offline_grace_carries_then_drops(make_coordinator):
    results = build_results()
    tracker = all_tracked_options()
    tracker[CONF_TRACKER_CONFIG][NEVER_SEEN] = {}
    coordinator, data = await run_once(make_coordinator, results, options=tracker)
    assert MAC1 in data["clients"]
    ip_before = data["clients"][MAC1]["ip_addr"]

    # 第二轮：路由器说它下线了，但还在 1 分钟缓冲内 → 沿用上一轮数据
    results[1] = {"data": []}
    data = await coordinator._async_update_data()
    coordinator.data = data
    assert data["clients"][MAC1]["ip_addr"] == ip_before
    assert MAC1 in data["clients"]

    # 缓冲期内、但上一轮 data 里已经没有该终端的记录 → 用占位字典兜底
    # （真实场景：协调器热重载后 self.data 被重置，_last_seen 仍在内存里）
    coordinator._last_seen[NEVER_SEEN] = time.time()
    data = await coordinator._async_update_data()
    coordinator.data = data
    assert data["clients"][NEVER_SEEN] == {
        "mac": NEVER_SEEN,
        "ip_addr": "unknown",
        "offline_buffering": True,
    }

    # 第三轮：缓冲期已过 → 真正离线，从映射里消失
    coordinator._last_seen[MAC1] = time.time() - 9999
    data = await coordinator._async_update_data()
    coordinator.data = data
    assert MAC1 not in data["clients"]


@pytest.mark.asyncio
async def test_never_seen_device_is_dropped_on_first_run(make_coordinator):
    """冷启动的_边界行为_：从未上报过的终端 elapsed 从 0 起算，直接判离线。

    这是个容易被误认为 bug 的既有行为，钉住它，将来若要改成「新设备先显示」会撞到这条。
    """
    options = {
        CONF_TRACKER_CONFIG: {MAC1: {}, NEVER_SEEN: {}},
        CONF_OFFLINE_GRACE_PERIOD: 60,
    }
    _, data = await run_once(make_coordinator, options=options)

    assert MAC1 in data["clients"]
    assert NEVER_SEEN not in data["clients"]


@pytest.mark.asyncio
async def test_per_device_buffer_overrides_global(make_coordinator):
    options = {
        CONF_TRACKER_CONFIG: {MAC1: {"buffer": 0}},  # 该设备不缓冲
        CONF_OFFLINE_GRACE_PERIOD: 60,
    }
    results = build_results()
    coordinator, _ = await run_once(make_coordinator, results, options=options)

    results[1] = {"data": []}
    data = await coordinator._async_update_data()

    assert MAC1 not in data["clients"]


@pytest.mark.asyncio
async def test_untracked_clients_are_ignored(make_coordinator):
    options = {CONF_TRACKER_CONFIG: {MAC1: {}}}
    _, data = await run_once(make_coordinator, options=options)

    assert set(data["clients"]) == {MAC1}


# ------------------------------------------------------------------ 接口 / 负载均衡


@pytest.mark.asyncio
async def test_interface_connectivity_rules(make_coordinator):
    _, data = await run_once(make_coordinator)
    ifaces = data["interfaces"]

    # 真实拨号线路：看 result
    assert ifaces["adsl0"]["connected"] is True
    assert ifaces["adsl0"]["is_wan_line"] is True
    assert ifaces["adsl0"]["protocol"] == "PPPOE"
    assert ifaces["adsl0"]["gateway"] == "1.2.3.1"
    assert ifaces["adsl1"]["connected"] is False

    # 聚合父口 wan1：任一子线路在线即在线
    assert ifaces["wan1"]["connected"] is True
    assert ifaces["wan1"]["parent_interface"] is None

    # 非 WAN 口：不算 WAN 线路
    assert ifaces["lan1"]["connected"] is False
    assert ifaces["lan1"]["is_wan_line"] is False


@pytest.mark.asyncio
async def test_aggregate_parent_offline_when_all_children_fail(make_coordinator):
    results = build_results()
    results[5]["iface_check"][0]["result"] = "fail"
    _, data = await run_once(make_coordinator, results)

    assert data["interfaces"]["wan1"]["connected"] is False


@pytest.mark.asyncio
async def test_interface_ip_placeholder_becomes_empty(make_coordinator):
    _, data = await run_once(make_coordinator)

    assert data["interfaces"]["adsl1"]["ip"] == ""
    assert data["interfaces"]["adsl0"]["ip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_has_v6_only_where_traffic_row_exists(make_coordinator):
    _, data = await run_once(make_coordinator)

    assert data["interfaces"]["adsl0"]["has_v6"] is True
    assert data["interfaces"]["adsl0"]["v6_upload_speed"] == 1048576
    assert data["interfaces"]["adsl1"]["has_v6"] is False
    assert data["interfaces"]["adsl1"]["v6_upload_speed"] == 0


@pytest.mark.asyncio
async def test_wan_balance_shares(make_coordinator):
    _, data = await run_once(make_coordinator)
    balance = data["wan_balance"]

    assert balance["_state"] == "2/3 在线"
    assert balance["lines"]["adsl0"]["download_share"] == 37.5
    assert balance["lines"]["adsl1"]["download_share"] == 12.5
    assert balance["lines"]["wan1"]["download_share"] == 50.0


@pytest.mark.asyncio
async def test_wan_balance_all_offline(make_coordinator):
    results = build_results()
    results[5] = {"iface_check": [], "iface_stream": []}
    _, data = await run_once(make_coordinator, results)

    assert data["wan_balance"]["_state"] == "全部离线"
    assert data["wan_balance"]["lines"] == {}


# ------------------------------------------------------------------ 存储 / 备份 / 安全 / 升级


@pytest.mark.asyncio
async def test_disk_usage_and_purpose_mapping(make_coordinator):
    _, data = await run_once(make_coordinator)
    disk = data["disks"]["sda"]

    assert disk["state"]["disk_usage_rate"] == 25.0  # 500 / 2000
    assert disk["state"]["disk_used_capacity"] == 500
    assert disk["partitions"][0]["usage"] == "25%"  # 已带百分号，不重复拼
    assert disk["partitions"][0]["purpose"] == "有余繁星"
    assert disk["partitions"][1]["usage"] == "未知"
    assert disk["partitions"][1]["purpose"] == "未知"


@pytest.mark.asyncio
async def test_latest_backup_picked_by_timestamp(make_coordinator):
    _, data = await run_once(make_coordinator)

    assert data["backup"]["latest_filename"] == "new.bak"
    assert data["backup"]["detail"]["version"] == "4.0.2"


@pytest.mark.asyncio
async def test_security_rules_keyed_by_id_and_missing_id_skipped(make_coordinator):
    _, data = await run_once(make_coordinator)

    assert data["security"]["mac_mode_code"] == 1
    assert set(data["security"]["mac_rules"]) == {"3"}


@pytest.mark.parametrize(
    ("status", "status_msg", "curr", "new", "expected"),
    [
        (1, "正在下载固件", "4.0.307", "4.0.308", "正在下载固件"),
        (2, "", "4.0.307", "4.0.308", "正在处理升级..."),
        (0, "", "4.0.307", "4.0.308", "发现新版本: 4.0.308"),
        (0, "", "4.0.307", "4.0.307", "已是最新版本"),
        (-1, "下载失败", "4.0.307", "4.0.308", "下载失败"),
    ],
)
@pytest.mark.asyncio
async def test_upgrade_display_state(
    make_coordinator, status, status_msg, curr, new, expected
):
    results = build_results()
    results[14]["data"]["system_ver"] = curr
    results[14]["data"]["new_system_ver"] = new
    results[15] = {"auto_upgrade": {"status": status, "status_msg": status_msg}}
    _, data = await run_once(make_coordinator, results)

    assert data["maintenance"]["upgrade_display_state"] == expected


# ------------------------------------------------------------------ 事件游标


@pytest.mark.asyncio
async def test_event_cold_start_emits_newest_then_increments(make_coordinator):
    results = build_results()
    coordinator, data = await run_once(make_coordinator, results)

    # 冷启动：只激活最新一条，不刷历史
    assert data["events"]["presence"] == [{"id": 3}]
    assert coordinator.last_presence_id == 3

    # 同一批数据再跑：无新事件
    data = await coordinator._async_update_data()
    assert data["events"]["presence"] == []

    # 出现 id=4 → 只发新的
    results[7] = {"data": [{"id": 4}, {"id": 3}, {"id": 2}]}
    data = await coordinator._async_update_data()
    assert data["events"]["presence"] == [{"id": 4}]
    assert coordinator.last_presence_id == 4


@pytest.mark.asyncio
async def test_event_supports_nested_results_envelope(make_coordinator):
    results = build_results()
    results[10] = {"results": {"data": [{"id": 21}, {"id": 20}]}}
    coordinator, data = await run_once(make_coordinator, results)

    assert data["events"]["system"] == [{"id": 21}]
    assert coordinator.last_system_log_id == 21


@pytest.mark.asyncio
async def test_event_slots_tolerate_bad_shapes(make_coordinator):
    """日志接口返回非 dict / 空 data / 缺 data 时都不能炸，也不能推进游标。"""
    results = build_results()
    results[7] = "not-a-dict"
    results[8] = {}
    results[9] = {"data": []}
    coordinator, data = await run_once(make_coordinator, results)

    assert data["events"]["presence"] == []
    assert data["events"]["ddns"] == []
    assert data["events"]["wifi"] == []
    assert coordinator.last_presence_id is None


@pytest.mark.asyncio
async def test_message_center_supports_nested_results_envelope(make_coordinator):
    results = build_results()
    results[6] = {"results": {"data": [{"type": "x", "title": "t", "detail": "d"}]}}
    _, data = await run_once(make_coordinator, results)

    assert data["events"]["messages"] == [{"type": "x", "title": "t", "detail": "d"}]


@pytest.mark.asyncio
async def test_message_center_dedup_by_content_signature(make_coordinator):
    results = build_results()
    results[6] = {
        "data": [
            {"type": "system", "title": "A", "detail": "1"},
            {"type": "system", "title": "B", "detail": "2"},
        ]
    }
    coordinator, data = await run_once(make_coordinator, results)
    assert len(data["events"]["messages"]) == 2

    data = await coordinator._async_update_data()
    assert data["events"]["messages"] == []

    results[6] = {
        "data": [
            {"type": "system", "title": "C", "detail": "3"},
            {"type": "system", "title": "A", "detail": "1"},
        ]
    }
    data = await coordinator._async_update_data()
    assert data["events"]["messages"] == [
        {"type": "system", "title": "C", "detail": "3"}
    ]


@pytest.mark.asyncio
async def test_message_signature_memory_is_trimmed(make_coordinator):
    results = build_results()
    coordinator, _ = await run_once(make_coordinator, results)
    coordinator._seen_msg_sigs = {f"sig-{i}" for i in range(250)}

    data = await coordinator._async_update_data()

    assert len(coordinator._seen_msg_sigs) == 100
    assert data["events"]["messages"] == [
        {"type": "system", "title": "备份完成", "detail": "ok"}
    ]


# ------------------------------------------------------------------ 容错


@pytest.mark.asyncio
async def test_exception_slots_degrade_to_empty(make_coordinator):
    results = build_results()
    results[0] = RuntimeError("system endpoint down")
    results[1] = None
    results[5] = RuntimeError("iface down")

    _, data = await run_once(make_coordinator, results)

    assert data["system"]["cpu_load"] == 0.0
    assert data["system"]["wan_ip_v4"] == "Disconnected"
    assert data["clients"] == {}
    assert data["interfaces"] == {}


@pytest.mark.asyncio
async def test_system_slot_without_sysinfo_key(make_coordinator):
    results = build_results()
    results[0] = {}
    _, data = await run_once(make_coordinator, results)

    assert data["system"]["cpu_load"] == 0.0
    assert data["system"]["uptime"] == 0
    assert data["system"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_api_failure_wrapped_as_update_failed(make_coordinator):
    coordinator = make_coordinator(build_results(), error=RuntimeError("boom"))

    with pytest.raises(coordinator_module.UpdateFailed, match="API 错误: boom"):
        await coordinator._async_update_data()


# ------------------------------------------------------------------ 设备信息


@pytest.mark.asyncio
async def test_device_info_properties(make_coordinator):
    coordinator, _ = await run_once(make_coordinator)

    info = coordinator.device_info
    assert info["identifiers"] == {("ikuai_connect", HOST)}
    assert info["sw_version"] == "4.0.307"
    assert info["hw_version"] == "arm64"
    assert info["name"].endswith("负载监控")

    assert coordinator.iface_mgmt_device_info["via_device"] == (
        "ikuai_connect",
        HOST,
    )
    assert coordinator.security_device_info["model"] == "Security & Firewall"
    assert coordinator.maintenance_device_info["model"] == "System Maintenance"


@pytest.mark.asyncio
async def test_gwid_falls_back_to_entry_id(make_coordinator):
    results = build_results()
    results[0] = system_slot(gwid=None)
    coordinator, _ = await run_once(make_coordinator, results)

    assert coordinator.gwid == coordinator.config_entry.entry_id
