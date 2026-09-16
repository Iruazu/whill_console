"""mock の露出・解像度（#53）。

実ドライバと同じ名前のパラメータを受けて、**画像が実際に変わる**こと。
変わらないと、スライダーが届いているかを実機なしで確かめられない。

`cv2` が要るので、入っていない環境（CI の ros-base）では skip される。
名前が実ドライバと一致しているかは `tests/services/test_camera_params.py`
が import せずに確かめる。
"""

from __future__ import annotations

import pytest

pytest.importorskip('cv2')
pytest.importorskip('rclpy')

from whill_mock_drivers.mock_realsense import (  # noqa: E402
    DEFAULT_PROFILE,
    NOMINAL_EXPOSURE_US,
    exposure_gain,
    parse_profile,
)


def test_profile_is_width_height_fps():
    assert parse_profile('640,480,6') == (640, 480, 6.0)
    assert parse_profile(' 320 , 240 , 15 ') == (320, 240, 15.0)
    assert parse_profile(DEFAULT_PROFILE) == (640, 480, 6.0)


@pytest.mark.parametrize('text', ['640,480', '640,480,6,1', '0,480,6', '640,-1,6', 'a,b,c', ''])
def test_broken_profile_is_rejected(text):
    """受理してから落ちると「スライダーを動かしたらカメラが消えた」になる。

    実ドライバの既定 `0,0,0`（ドライバ任せ）も、モックには絵の大きさが
    決まらないので拒否する。
    """
    with pytest.raises(ValueError):
        parse_profile(text)


def test_auto_exposure_ignores_the_manual_value():
    assert exposure_gain(auto=True, exposure_us=10000) == 1.0
    assert exposure_gain(auto=True, exposure_us=1) == 1.0


def test_manual_exposure_changes_brightness():
    assert exposure_gain(auto=False, exposure_us=NOMINAL_EXPOSURE_US) == 1.0
    assert exposure_gain(auto=False, exposure_us=NOMINAL_EXPOSURE_US * 2) == pytest.approx(2.0)
    assert exposure_gain(auto=False, exposure_us=NOMINAL_EXPOSURE_US // 2) < 1.0
