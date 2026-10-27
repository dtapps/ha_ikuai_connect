"""测试数据：与 api.get_all_data() 的 17 个槽位一一对应。

协调器、平台、服务三条测试线共用同一份数据，保证「同一份路由器快照」
在所有断言里说法一致。顺序即 api.get_all_data 的返回顺序，不能重排。
"""

from __future__ import annotations

# 被测终端：第一台走完整流程（在线 → 缓冲 → 离线）
MAC1 = "08:9b:4b:01:7e:7c"
MAC2 = "aa:bb:cc:dd:ee:02"
MAC3 = "aa:bb:cc:dd:ee:03"
MAC4 = "aa:bb:cc:dd:ee:04"
NEVER_SEEN = "aa:bb:cc:dd:ee:05"  # 只在 tracker_config 里，从未被路由器上报

GWID = "gw-123"
HOST = "https://10.10.10.1"


def system_slot(**sysinfo_overrides):
    """槽位 0：系统状态。"""
    sysinfo = {
        "cpu": ["12%", "10%", "8%", "6%"],
        "memory": {
            "total": 8388608,
            "used": "45%",
            "available": 4194304,
            "free": 2097152,
            "cached": 1048576,
            "buffers": 65536,
        },
        "uptime": 3725,
        "cputemp": [45, 47],
        "verinfo": {
            "version": "4.0.307",
            "verstring": "4.0.307-beta x64 Build202608051709",
            "arch": "arm64",
        },
        "online_user": {
            "count": 7,
            "count_wired": 2,
            "count_2g": 1,
            "count_5g": 3,
            "count_wireless": 4,
        },
        "stream": {
            "upload": 1024,
            "download": 2048,
            "total_up": 10**9,
            "total_down": 2 * 10**9,
            "connect_num": 300,
            "tcp_connect_num": 200,
            "udp_connect_num": 90,
            "icmp_connect_num": 10,
        },
        "hostname": "ikuai-home",
        "gwid": GWID,
    }
    sysinfo.update(sysinfo_overrides)
    return {"sysinfo": sysinfo}


def clients_slot():
    """槽位 1：在线终端。覆盖名称回退链的每一种分支。"""
    return {
        "data": [
            {
                "mac": "08-9B-4B-01-7E-7C",
                "termname": "小米%20Pad",
                "ip_addr": "192.168.1.10",
                "client_vendor": "Xiaomi",
            },
            {
                "mac": MAC2,
                "termname": "",
                "client_model": "iPhone%2015",
                "ip_addr": "192.168.1.11",
            },
            {"mac": MAC3, "comment": "客厅(电视盒子)", "ip_addr": "192.168.1.12"},
            {"mac": MAC4, "ip_addr": "192.168.1.13"},
            {"ip_addr": "192.168.1.99"},  # 无 mac，必须被跳过
        ]
    }


def wifi_stats_slot():
    """槽位 2：无线统计。"""
    return {
        "ap_status": {
            "ap_online": 2,
            "ap_count": 3,
            "ap_offline": 1,
            "ap_roaming": True,
            "ap_perfer_5g": 1,
        },
        "clt_status": {"clt_count_2g": 1, "clt_count_5g": 3, "clt_active": 4},
    }


def wifi_score_slot():
    """槽位 3：无线评分。"""
    return {
        "total_count_net_status": {
            "coverage": 96,
            "delay": 8,
            "dropptk": 0.5,
            "score_chutil_load": 88,
        }
    }


def v6_slot():
    """槽位 4：IPv6 线路流量（只有 adsl0 开了 v6）。"""
    return {
        "data": [
            {
                "interface": "adsl0",
                "upload": 1048576,  # 1 MB/s
                "download": 2097152,  # 2 MB/s
                "total_upload": 5_000_000_000,
                "total_download": 6_000_000_000,
                "conn": 12,
            }
        ]
    }


def iface_status_slot():
    """槽位 5：线路状态。含真实拨号线、聚合父口、LAN 口三种形态。"""
    return {
        "iface_check": [
            {
                "interface": "adsl0",
                "parent_interface": "wan1",
                "ip_addr": "1.2.3.4",
                "result": "success",
                "internet": "PPPOE",
                "gateway": "1.2.3.1",
                "auto_switch": "yes",
                "errmsg": "",
            },
            {
                "interface": "adsl1",
                "parent_interface": "wan1",
                "ip_addr": "--",
                "result": "fail",
            },
        ],
        "iface_stream": [
            {
                "interface": "adsl0",
                "ip_addr": "1.2.3.4",
                "upload": 100,
                "download": 300,
                "total_up": 1,
                "total_down": 2,
            },
            {
                "interface": "adsl1",
                "ip_addr": "--",
                "upload": 0,
                "download": 100,
                "total_up": 0,
                "total_down": 0,
            },
            {
                "interface": "wan1",
                "ip_addr": "--",
                "upload": 100,
                "download": 400,
                "total_up": 5,
                "total_down": 6,
            },
            {
                "interface": "lan1",
                "ip_addr": "192.168.1.1",
                "upload": 10,
                "download": 20,
                "total_up": 30,
                "total_down": 40,
            },
        ],
    }


def message_center_slot():
    """槽位 6：消息中心（无 id，靠内容签名去重）。"""
    return {"data": [{"type": "system", "title": "备份完成", "detail": "ok"}]}


def presence_slot():
    """槽位 7：上下线日志（id 降序）。"""
    return {"data": [{"id": 3}, {"id": 2}, {"id": 1}]}


def ddns_slot():
    return {"data": [{"id": 10}]}


def wireless_log_slot():
    return {"data": [{"id": 5}]}


def system_log_slot():
    return {"data": [{"id": 7}]}


def mac_mode_slot():
    """槽位 11：全局访问控制模式（1 = 白名单）。"""
    return {"acl_mac": 1}


def mac_rules_slot():
    """槽位 12：MAC 规则。第二条没有 id，必须被丢弃。"""
    return {"data": [{"id": 3, "mac": "aa", "enabled": "yes"}, {"mac": "no-id"}]}


def backup_slot():
    """槽位 13：备份列表（按 timestamp 取最新）。"""
    return {
        "backup_info": [
            {
                "filename": "old.bak",
                "timestamp": 100,
                "backtype": "manual",
                "filesize": 10,
                "version": "4.0.1",
            },
            {
                "filename": "new.bak",
                "timestamp": 200,
                "backtype": "auto",
                "filesize": 20,
                "version": "4.0.2",
            },
        ]
    }


def upgrade_info_slot():
    """槽位 14：升级信息。"""
    return {
        "data": {
            "system_ver": "4.0.307",
            "new_system_ver": "4.0.308",
            "version_type": "stable",
            "build_date": "20260801",
            "update_content": "修复若干问题",
        }
    }


def upgrade_status_slot():
    """槽位 15：升级进度（0 = 空闲）。"""
    return {"auto_upgrade": {"status": 0, "status_msg": ""}}


def disks_slot():
    """槽位 16：磁盘。两个分区各覆盖一种 usage / purpose 写法。"""
    return {
        "data": [
            {
                "disk": "sda",
                "model": "SSD-X",
                "type": "ssd",
                "size": "128G",
                "system": "yes",
                "block_size": "512",
                "partition": [
                    {
                        "name": "sda1",
                        "mounted": {
                            "mt_total": 1000,
                            "mt_used": 250,
                            "mt_uses": "25%",
                            "mt_name": "/",
                            "mt_purpose": 1,
                        },
                    },
                    {
                        "name": "sda2",
                        "mounted": {
                            "mt_total": 1000,
                            "mt_used": "250",
                            "mt_uses": None,
                            "mt_purpose": "9",
                        },
                    },
                ],
            }
        ]
    }


def build_results() -> list:
    """17 个槽位，顺序与 api.get_all_data 完全一致。"""
    return [
        system_slot(),
        clients_slot(),
        wifi_stats_slot(),
        wifi_score_slot(),
        v6_slot(),
        iface_status_slot(),
        message_center_slot(),
        presence_slot(),
        ddns_slot(),
        wireless_log_slot(),
        system_log_slot(),
        mac_mode_slot(),
        mac_rules_slot(),
        backup_slot(),
        upgrade_info_slot(),
        upgrade_status_slot(),
        disks_slot(),
    ]


# ---------------------------------------------------------------- 服务层数据


def traffic_summary() -> dict:
    """get_client_traffic_summary 的返回体（单位为字节）。"""
    mb = 1024 * 1024
    return {
        "terminal_total_flow": 3 * mb,
        "terminal": [
            {
                "mac": MAC1,
                "ip_addr": "192.168.1.10",
                "termname": "小米%20Pad",
                "sum_total": 2 * mb,
                "sum_total_up": mb // 2,
                "sum_total_down": 3 * mb // 2,
            },
            {
                "mac": MAC2,
                "ip_addr": "192.168.1.11",
                "comment": "爸爸的手机",
                "sum_total": mb,
                "sum_total_up": mb // 4,
                "sum_total_down": 3 * mb // 4,
            },
        ],
    }


def protocol_stats() -> dict:
    """get_client_protocol_stats 的返回体。"""
    mb = 1024 * 1024
    return {
        "data": [
            {"proto_name": "HTTP", "total": mb},
            {"proto_name": "P2P", "total": 3 * mb},
            {"proto_name": "DNS", "total": 0},  # 0 流量必须被过滤
        ]
    }


def offline_history() -> dict:
    """get_offline_history 的返回体。"""
    return {
        "offline_data": [
            {
                "mac": MAC4,
                "ip_addr": "192.168.1.13",
                "termname": "旧平板",
                "total_up": 1024 * 1024,
                "total_down": 1024 * 1024,
                "logout_time": 1_760_000_000,
                "client_type": "wifi",
                "client_vendor": "Apple",
            },
            {
                "mac": "aa:bb:cc:dd:ee:99",
                "ip_addr": "192.168.1.99",
                "logout_time": 0,  # 无下线时间 → "Unknown"
            },
        ]
    }
