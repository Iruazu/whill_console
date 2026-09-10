"""gateway のフレーム定義のテスト。

`protocol.py` は websockets にも rclpy にも依存しないので、ここは
どこでも走る。フレームの形が変わったことを、通信を動かさずに捕まえる。
"""

from __future__ import annotations

import json

import pytest

from whill_gateway import protocol


# ---- パース ----------------------------------------------------------------


def test_parses_a_valid_message():
    message = protocol.parse_client_message('{"type": "heartbeat", "seq": 3}')
    assert message['type'] == 'heartbeat'
    assert message['seq'] == 3


def test_accepts_bytes():
    assert protocol.parse_client_message(b'{"type": "heartbeat"}')['type'] == 'heartbeat'


@pytest.mark.parametrize('raw,fragment', [
    ('not json', 'JSON として読めない'),
    ('[]', 'オブジェクトでない'),
    ('{}', 'type が無い'),
    ('{"type": 5}', 'type が無いか文字列でない'),
    ('{"type": "drop_database"}', '未知の type'),
])
def test_rejects_bad_messages(raw, fragment):
    """WebSocket には任意の JSON を投げられる。UI 側の検査を信頼しない。"""
    with pytest.raises(protocol.ProtocolError, match=fragment):
        protocol.parse_client_message(raw)


def test_rejects_invalid_utf8():
    with pytest.raises(protocol.ProtocolError, match='UTF-8'):
        protocol.parse_client_message(b'\xff\xfe')


def test_require_reports_missing_field():
    with pytest.raises(protocol.ProtocolError, match='token が無い'):
        protocol.require({'type': 'auth'}, 'token', str)


def test_require_rejects_wrong_type():
    with pytest.raises(protocol.ProtocolError, match='型が不正'):
        protocol.require({'type': 'auth', 'token': 5}, 'token', str)


def test_require_rejects_bool_where_number_expected():
    """bool は int の派生。数値の場所に True を通さない。"""
    with pytest.raises(protocol.ProtocolError, match='bool'):
        protocol.require({'type': 'manual_vel', 'vx': True}, 'vx', float)


# ---- subscribe -------------------------------------------------------------


def test_subscribe_defaults_when_omitted():
    assert protocol.parse_subscribe({'type': 'subscribe'}) == protocol.DEFAULT_STREAMS


def test_subscribe_rejects_unknown_stream():
    """typo を「黙って何も届かない」に変えない。"""
    with pytest.raises(protocol.ProtocolError, match='未知のストリーム'):
        protocol.parse_subscribe({'type': 'subscribe', 'streams': ['costmpa']})


def test_subscribe_rejects_non_list():
    with pytest.raises(protocol.ProtocolError, match='配列でない'):
        protocol.parse_subscribe({'type': 'subscribe', 'streams': 'costmap'})


def test_default_streams_exclude_expensive_ones():
    """画像と tf は明示的に要求させる。既定で流すと帯域を無駄にする。"""
    assert protocol.MSG_IMAGE not in protocol.DEFAULT_STREAMS
    assert protocol.MSG_TF not in protocol.DEFAULT_STREAMS
    assert protocol.MSG_COSTMAP in protocol.DEFAULT_STREAMS


def test_streams_are_all_server_messages():
    """購読できるストリームは全て server → client のフレームであること。"""
    assert protocol.STREAMS <= {
        protocol.MSG_STATUS, protocol.MSG_PARAMS, protocol.MSG_COSTMAP,
        protocol.MSG_COSTMAP_UPDATE, protocol.MSG_POSE, protocol.MSG_PATH,
        protocol.MSG_TF, protocol.MSG_DIAGNOSTICS, protocol.MSG_IMAGE,
    }


# ---- 認証前に流してよいもの ------------------------------------------------


def test_pre_auth_messages_contain_no_data_frames():
    """認証前にテレメトリが 1 種類でも混ざっていたら設計違反。"""
    data_frames = {
        protocol.MSG_COSTMAP, protocol.MSG_POSE, protocol.MSG_PATH,
        protocol.MSG_TF, protocol.MSG_DIAGNOSTICS, protocol.MSG_IMAGE,
        protocol.MSG_PARAMS, protocol.MSG_STATUS,
    }
    assert protocol.PRE_AUTH_MESSAGES & data_frames == set()


# ---- フレーム構築 ----------------------------------------------------------


def test_hello_carries_protocol_version():
    frame = protocol.hello(robot_id='cr2-01', mode='mock', authenticated=False)
    assert frame['protocol'] == protocol.PROTOCOL_VERSION
    assert frame['authenticated'] is False


def test_error_always_states_a_reason():
    """黙って切らない。理由が無いと切り分けができない。"""
    frame = protocol.error('トークンが違う', fatal=True)
    assert frame['reason']
    assert frame['fatal'] is True


def test_status_carries_estop():
    frame = protocol.status(robot_id='cr2-01', mode='mock', nav_active=True,
                            estop=True, clients=2, stamp=1.0)
    assert frame['estop'] is True
    assert frame['clients'] == 2


# ---- エンコード ------------------------------------------------------------


def test_encode_keeps_japanese_unescaped():
    """説明文は日本語。エスケープすると帯域が 3 倍近くになる。"""
    text = protocol.encode({'type': 'error', 'reason': '範囲外'})
    assert '範囲外' in text
    assert '\\u' not in text


def test_encode_rejects_nan():
    """NaN を含む JSON はブラウザの JSON.parse で落ちる。送信側で止める。"""
    with pytest.raises(ValueError):
        protocol.encode({'type': 'pose', 'x': float('nan')})


def test_safe_encode_scrubs_nan_to_null():
    """テレメトリは 1 フレーム壊れても次が来る。値だけ落として流し続ける。"""
    text = protocol.safe_encode({'type': 'pose', 'x': float('nan'), 'y': 1.0})
    assert json.loads(text) == {'type': 'pose', 'x': None, 'y': 1.0}


def test_safe_encode_scrubs_infinity():
    text = protocol.safe_encode({'type': 'pose', 'x': float('inf')})
    assert json.loads(text)['x'] is None


def test_safe_encode_recurses_into_containers():
    text = protocol.safe_encode({'type': 'path', 'pts': [{'x': float('nan')}]})
    assert json.loads(text)['pts'][0]['x'] is None


def test_encode_is_compact():
    """costmap を毎秒流すので、区切りの空白も惜しむ。"""
    assert ', ' not in protocol.encode({'type': 'status', 'a': 1, 'b': 2})


# ---- ストリームの帰属 ------------------------------------------------------


def test_costmap_update_belongs_to_the_costmap_stream():
    """部分更新を独立したストリームにしない。

    独立させると「costmap は購読しているのに部分更新が来ない」構成を
    作れてしまい、地図が最初の 1 枚で固まる（ADR-0002 の失敗そのもの）。
    実際、この対応表を入れる前は broadcast で捨てられていた。
    """
    assert protocol.stream_of(protocol.MSG_COSTMAP_UPDATE) == protocol.MSG_COSTMAP


def test_stream_of_is_identity_for_plain_frames():
    for kind in (protocol.MSG_POSE, protocol.MSG_PATH, protocol.MSG_TF):
        assert protocol.stream_of(kind) == kind


def test_costmap_update_is_not_separately_subscribable():
    """subscribe で costmap_update を選べないこと（選ばせると混乱する）。"""
    assert protocol.MSG_COSTMAP_UPDATE not in protocol.STREAMS
