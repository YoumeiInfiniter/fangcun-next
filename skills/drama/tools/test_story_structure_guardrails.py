#!/usr/bin/env python3
from story_structure_guardrails import validate_script_scene_keys, validate_text


def test_consecutive_same_scene_is_error():
    text = """1-1

场：星阳体育馆-日-内
△主角站在场边。

1-2

场：星阳体育馆-日-内
△反派冷笑。
"""
    result = validate_text(text)
    assert result["ok"] is False
    assert result["issues"][0]["type"] == "same_scene_key_split"


def test_big_scene_with_subarea_marker_still_must_be_merged():
    text = """1-1

场：星阳体育馆-日-内
△看台上，观众全部起身。

1-2

场：星阳体育馆-日-内
△解说席，主持人拍桌。
"""
    result = validate_text(text)
    assert result["ok"] is False
    assert result["issues"][0]["type"] == "same_scene_key_split"


def test_standard_scene_heading_same_time_place_io_is_error():
    text = """8-1　京城救灾议事厅　日　内
△青禾把棋子按在十里亭。
青禾（柔声）：物资统一送十里亭。

8-2　京城救灾议事厅　日　内
△陆莞拿起三枚黑棋，依次压在官道、棚区、空白仓位。
陆莞（冷声）：第一日热闹，第七日抬尸。
"""
    result = validate_text(text)
    assert result["ok"] is False
    assert result["issues"][0]["previous_scene"] == "8-1"
    assert result["issues"][0]["current_scene"] == "8-2"
    assert result["issues"][0]["scene_key"] == "京城救灾议事厅|日|内"


def test_validate_script_scene_keys_is_hard_gate_only():
    text = """1-1　祖母院　日　内
△陆莞进门。

1-2　祖母院　日　内
△周管事冲进来。
"""
    result = validate_script_scene_keys(text)
    assert result["ok"] is False
    assert result["issue_count"] == 1


def test_time_label_only_split_is_error_without_visible_time_jump():
    text = """2-1　祖母院正厅　日　内
△陆莞扣下茶盖。
陆莞：赏可以，不能压嫡。

2-2　祖母院正厅　午　内
△周管事带着两个小厮跪进来。
周管事：库房衣料生了虫眼。
"""
    result = validate_script_scene_keys(text)
    assert result["ok"] is False
    assert result["issues"][0]["type"] == "time_label_only_split"


def test_same_place_time_split_allowed_with_visible_time_jump():
    text = """2-1　祖母院正厅　日　内
△陆莞扣下茶盖。
△众人散去，祖母让人重新收拾杯盏。

2-2　祖母院正厅　午　内
△午膳后，窗外日影移到门槛，小厮捧着库房册进来。
周管事：库房衣料生了虫眼。
"""
    result = validate_script_scene_keys(text)
    assert result["ok"] is True


def test_episode_volume_unbalanced_is_warning_not_error():

    text = """第1集
A
B
C
D
E
F
G
H
第2集
A
第3集
A
B
C
D
E
F
G
H
I
J
K
L
M
N
O
P
Q
R
S
T
"""
    result = validate_text(text)
    assert result["ok"] is True
    assert any(i["type"] == "episode_volume_unbalanced" for i in result["issues"])


if __name__ == "__main__":
    test_consecutive_same_scene_is_error()
    test_big_scene_with_subarea_marker_still_must_be_merged()
    test_standard_scene_heading_same_time_place_io_is_error()
    test_validate_script_scene_keys_is_hard_gate_only()
    test_time_label_only_split_is_error_without_visible_time_jump()
    test_same_place_time_split_allowed_with_visible_time_jump()
    test_episode_volume_unbalanced_is_warning_not_error()
    print("ok")
