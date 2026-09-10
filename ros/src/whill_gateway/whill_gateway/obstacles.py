"""仮想障害物の保持と検査。

**rclpy に依存しない。** 素の辞書を扱うだけなので、ROS を立てずに検証できる。
ROS への publish は gateway が行う。

## 全量置換にしている理由

costmap 層は毎回すべての障害物を受け取る（`whill_costmap_plugins`）。
差分にすると、UI と costmap の状態がずれたときに復旧できない — どちらが
正しいか分からず、片方を消しても消えない障害物が残る。数は高々数十なので
毎回全部でよい。

したがって gateway は**現在の一覧を保持する**必要がある。1 個足すたびに
全部送り直すため。

## 保持するだけで永続化しない

gateway を再起動すると消える。ファイルに残さない理由:

仮想障害物は「この配置だとどうなるか」を試す道具で、置きっぱなしにする
ものではない。永続化すると、**前のセッションで置いた障害物が生きたまま
実機の走行に影響する**という一番まずい形の忘れ方ができる。

代わりに、置いている個数を UI に常時出して忘れられないようにする（#31）。
「再起動したら消えていた」で驚くほうが、「消したつもりが残っていた」より
被害が小さい。
"""

from __future__ import annotations

import math
from typing import Any

MAX_RADIUS_M = 5.0
"""半径の上限。costmap 層の `max_radius` と揃えること。

巨大な円を置かれると costmap が埋まる。層側でも丸めるが、こちらで弾いて
「なぜ小さくなったのか」を UI に返せるようにする。
"""

MIN_RADIUS_M = 0.05
"""下限。costmap の解像度（0.05 m）より小さい円は 1 セルも塗れず、
「置いたのに何も起きない」ことになる。"""

MAX_OBSTACLES = 200
"""個数の上限。1 クライアントが流し込んで costmap を埋めるのを防ぐ。"""

ALLOWED_FRAME = 'map'
"""受け付ける frame_id。

俯瞰図のクリックから作るので map 以外を使う場面が無い。**決め打ちにする。**
将来 base_link 基準で置きたくなったら、そのとき変換を入れて広げる。
いま曖昧にしておくと「どの座標系で置いたのか分からない障害物」ができる。
"""


class ObstacleError(Exception):
    """受け取った障害物が契約を満たしていない。"""


def validate(raw: Any) -> dict[str, Any]:
    """1 個ぶんを検査して正規化する。

    WebSocket には任意の JSON を投げられるので、UI 側の検査を信頼しない。
    """
    if not isinstance(raw, dict):
        raise ObstacleError('障害物がオブジェクトでない')

    identifier = raw.get('id')
    if not isinstance(identifier, str) or not identifier:
        raise ObstacleError('id が無いか文字列でない')

    frame_id = raw.get('frame_id', ALLOWED_FRAME)
    if frame_id != ALLOWED_FRAME:
        raise ObstacleError(
            f'frame_id は "{ALLOWED_FRAME}" のみ受け付ける (受信値 {frame_id!r})')

    x = _finite(raw.get('x'), 'x')
    y = _finite(raw.get('y'), 'y')
    radius = _finite(raw.get('radius'), 'radius')

    if radius < MIN_RADIUS_M:
        raise ObstacleError(
            f'半径 {radius} m が小さすぎる（{MIN_RADIUS_M} m 未満は 1 セルも塗れない）')
    if radius > MAX_RADIUS_M:
        raise ObstacleError(f'半径 {radius} m が上限 {MAX_RADIUS_M} m を超えている')

    return {'id': identifier, 'frame_id': ALLOWED_FRAME,
            'x': x, 'y': y, 'radius': radius}


def _finite(value: Any, field: str) -> float:
    # bool は int の派生。数値の場所に True を通さない。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObstacleError(f'{field} が数値でない')
    number = float(value)
    if not math.isfinite(number):
        # NaN を通すと costmap の全域が塗られたり無限ループになる。
        raise ObstacleError(f'{field} が有限でない')
    return number


class ObstacleStore:
    """現在置かれている仮想障害物。

    順序は保持する。UI の一覧表示で並びが毎回変わると追いにくい。
    """

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def all(self) -> list[dict[str, Any]]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    # ---- 操作 --------------------------------------------------------------

    def replace(self, raws: Any) -> list[dict[str, Any]]:
        """全量置換。UI の状態をそのまま反映する。"""
        if not isinstance(raws, list):
            raise ObstacleError('obstacles が配列でない')
        if len(raws) > MAX_OBSTACLES:
            raise ObstacleError(f'個数が上限 {MAX_OBSTACLES} を超えている')

        validated = [validate(raw) for raw in raws]
        seen: set[str] = set()
        for item in validated:
            if item['id'] in seen:
                # 重複を黙って潰すと「消したのに残る」ことになる。
                raise ObstacleError(f'id が重複している: {item["id"]}')
            seen.add(item['id'])

        self._items = {item['id']: item for item in validated}
        return self.all()

    def add(self, raw: Any) -> list[dict[str, Any]]:
        item = validate(raw)
        if item['id'] not in self._items and len(self._items) >= MAX_OBSTACLES:
            raise ObstacleError(f'個数が上限 {MAX_OBSTACLES} に達している')
        # 同じ id なら上書き。UI がドラッグで半径を変える操作を想定している。
        self._items[item['id']] = item
        return self.all()

    def remove(self, identifier: Any) -> list[dict[str, Any]]:
        if not isinstance(identifier, str) or not identifier:
            raise ObstacleError('id が無いか文字列でない')
        if identifier not in self._items:
            # 消えているものを消そうとしただけ。エラーにしない
            # （二重クリックや、他のクライアントが先に消した場合）。
            return self.all()
        del self._items[identifier]
        return self.all()

    def clear(self) -> list[dict[str, Any]]:
        self._items = {}
        return self.all()


def apply_command(store: ObstacleStore, message: dict[str, Any]) -> list[dict[str, Any]]:
    """クライアントからの 1 コマンドを適用し、適用後の全量を返す。

    未知の action は黙って無視せずエラーにする。黙って捨てると、UI 側は
    「送ったのに効かない」理由を追えない。
    """
    action = message.get('action', 'replace')
    if action == 'replace':
        return store.replace(message.get('obstacles', []))
    if action == 'add':
        return store.add(message.get('obstacle'))
    if action == 'remove':
        return store.remove(message.get('id'))
    if action == 'clear':
        return store.clear()
    raise ObstacleError(f'未知の action: {action}')
