"""helpers 模块单元测试：终端名解码、标签提取、MAC 归一化。"""

from __future__ import annotations

import pytest

from custom_components.ikuai_connect import helpers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("小米%20Pad%208%20Pro", "小米 Pad 8 Pro"),
        ("MacBook%2DPro", "MacBook-Pro"),
        ("客厅%20电视", "客厅 电视"),
        ("plain-name", "plain-name"),
        ("  zhangsan  ", "zhangsan"),
        ("100%25", "100%"),
        # 非法百分号编码原样保留，不抛异常
        ("50%", "50%"),
    ],
)
def test_decode_term_name(raw, expected):
    assert helpers.decode_term_name(raw) == expected


@pytest.mark.parametrize("empty", ["", None])
def test_decode_term_name_empty(empty):
    assert helpers.decode_term_name(empty) == ""


def test_decode_term_name_passes_through_non_string():
    """非字符串原样透传（当前实现如此），关键是别崩。"""
    assert helpers.decode_term_name(123) == 123
    assert helpers.decode_term_name(False) == ""


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # 括号内容优先：iKuai 备注格式常用「备注(真名)」
        ("客厅路由(xiaomi-ax6000)", "xiaomi-ax6000"),
        ("(only-in-paren)", "only-in-paren"),
        ("(  padded  )", "padded"),
        # 无括号时退化为整体去空白
        ("  无括号备注  ", "无括号备注"),
        # URL 编码先解码，再找括号
        ("room%20A(dev%201)", "dev 1"),
        # 多个括号只取第一个
        ("a(b)c(d)", "b"),
    ],
)
def test_extract_name_from_label(label, expected):
    assert helpers.extract_name_from_label(label) == expected


@pytest.mark.parametrize("empty", ["", None])
def test_extract_name_from_label_empty(empty):
    assert helpers.extract_name_from_label(empty) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08-9B-4B-01-7E-7C", "08:9b:4b:01:7e:7c"),
        ("08:9B:4B:01:7E:7C", "08:9b:4b:01:7e:7c"),
        ("A.B.C.D.E.F", "a:b:c:d:e:f"),
        ("  08-9b-4b-01-7e-7c  ", "08:9b:4b:01:7e:7c"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_mac(raw, expected):
    assert helpers.normalize_mac(raw) == expected


def test_normalize_mac_is_idempotent():
    once = helpers.normalize_mac("08-9B-4B-01-7E-7C")
    assert helpers.normalize_mac(once) == once
