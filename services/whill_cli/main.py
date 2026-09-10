"""`whill` CLI。

Phase 0 の受け入れ条件はこのコマンド:

    whill run --robot cr2-01 --mode mock

これで Nav2 + モックが起動し、`ros2 topic list` に宣言トピックが揃うこと。
突き合わせは `whill doctor` が自動でやる。
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys

import typer
from rich.console import Console
from rich.table import Table

from whill_cli import config

app = typer.Typer(
    add_completion=False,
    help='whill_platform の開発・運用 CLI',
    no_args_is_help=True,
)
params_app = typer.Typer(help='パラメータ registry の参照', no_args_is_help=True)
stack_app = typer.Typer(help='スタックの起動・停止 (stackd 経由)', no_args_is_help=True)
app.add_typer(params_app, name='params')
app.add_typer(stack_app, name='stack')

console = Console()


def _ros_env() -> dict[str, str]:
    """launch に渡す環境。config の位置を必ず伝える。"""
    env = dict(os.environ)
    env.setdefault('WHILL_PLATFORM_CONFIG', str(config.config_root()))
    # 既存リポで実証済み: FastDDS は VelodyneScan 級の大メッセージで詰まる
    env.setdefault('RMW_IMPLEMENTATION', 'rmw_cyclonedds_cpp')
    return env


def _ros_setup_hint() -> str:
    ws = config.repo_root() / 'ros' / 'install' / 'setup.bash'
    return f'source {ws}' if ws.is_file() else 'colcon build を先に実行すること'


# ---- run -------------------------------------------------------------------


@app.command()
def run(
    robot: str = typer.Option('cr2-01', '--robot', '-r', help='個体 ID'),
    mode: str = typer.Option('mock', '--mode', '-m', help='real / sim / replay / mock'),
    preset: str = typer.Option('', '--preset', '-p', help='config/presets/<name>'),
    bag: str = typer.Option('', '--bag', help='mode=replay のときの MCAP パス'),
    camera: bool = typer.Option(False, '--camera', help='realsense を追加起動する'),
    gateway: bool = typer.Option(False, '--gateway', help='whill_gateway も起動する'),
    dry_run: bool = typer.Option(False, '--dry-run', help='起動せずコマンドだけ表示'),
) -> None:
    """スタックを起動する。"""
    robots = config.known_robots()
    if robot not in robots:
        console.print(f'[red]未知の個体: {robot}[/red] (候補: {", ".join(robots)})')
        raise typer.Exit(2)

    modes = config.known_modes()
    if mode not in modes:
        console.print(f'[red]未知のモード: {mode}[/red] (候補: {", ".join(modes)})')
        raise typer.Exit(2)

    if preset and preset not in config.known_presets():
        console.print(f'[red]未知の preset: {preset}[/red] '
                      f'(候補: {", ".join(config.known_presets())})')
        raise typer.Exit(2)

    if mode == 'replay' and not bag:
        console.print('[red]mode=replay には --bag が必要[/red]')
        raise typer.Exit(2)

    # preset の real_robot_allowed: false を実機で使わせない。原則 4 の一部で、
    # bench-replay のような描画優先設定を実機に持ち込むと CPU を食い潰す。
    if preset:
        preset_data = config.load_yaml(config.config_root() / 'presets' / f'{preset}.yaml')
        if preset_data.get('real_robot_allowed') is False and mode == 'real':
            console.print(f'[red]preset "{preset}" は実機で使えない '
                          f'(real_robot_allowed: false)[/red]')
            raise typer.Exit(2)

    cmd = [
        'ros2', 'launch', 'whill_bringup', 'bringup_launch.py',
        f'robot_id:={robot}', f'mode:={mode}',
        f'use_camera:={str(camera).lower()}', f'gateway:={str(gateway).lower()}',
    ]
    if preset:
        cmd.append(f'preset:={preset}')
    if bag:
        cmd.append(f'bag:={bag}')

    console.print(f'[bold]{shlex.join(cmd)}[/bold]')
    if dry_run:
        return

    env = _ros_env()
    try:
        process = subprocess.Popen(cmd, env=env)
    except FileNotFoundError:
        console.print(f'[red]ros2 が見つからない。{_ros_setup_hint()}[/red]')
        raise typer.Exit(2) from None

    def _forward(signum, _frame):
        # ros2 launch の子プロセスは SIGINT が確実には伝播しない。まず INT を
        # 送り、落ちなければ呼び出し側が改めて止める（既存リポの教訓）。
        process.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, _forward)
    signal.signal(signal.SIGTERM, _forward)
    raise typer.Exit(process.wait())


# ---- doctor ----------------------------------------------------------------


@app.command()
def doctor(
    robot: str = typer.Option('cr2-01', '--robot', '-r'),
    mode: str = typer.Option('mock', '--mode', '-m'),
    camera: bool = typer.Option(False, '--camera'),
) -> None:
    """走っているスタックが宣言どおりのトピックを出しているか突き合わせる。

    Phase 0 の受け入れ判定はこれ。人が `ros2 topic list` を目で見るのではなく、
    cr2-base.yaml の宣言を正として機械的に判定する。
    """
    expected = config.declared_topics(robot, mode, include_camera=camera)

    try:
        result = subprocess.run(['ros2', 'topic', 'list'], capture_output=True,
                                text=True, timeout=20, env=_ros_env(), check=False)
    except FileNotFoundError:
        console.print(f'[red]ros2 が見つからない。{_ros_setup_hint()}[/red]')
        raise typer.Exit(2) from None
    except subprocess.TimeoutExpired:
        console.print('[red]ros2 topic list がタイムアウトした[/red]')
        raise typer.Exit(2) from None

    actual = {line.strip() for line in result.stdout.splitlines() if line.strip()}

    table = Table(title=f'{robot} / mode={mode} — 宣言トピックの充足')
    table.add_column('topic')
    table.add_column('状態')
    missing = []
    for topic in expected:
        if topic in actual:
            table.add_row(topic, '[green]OK[/green]')
        else:
            table.add_row(topic, '[red]MISSING[/red]')
            missing.append(topic)
    console.print(table)

    if missing:
        console.print(f'[red]{len(missing)} 件が出ていない[/red]')
        raise typer.Exit(1)
    console.print(f'[green]宣言された {len(expected)} 件すべて publish されている[/green]')


# ---- tap -------------------------------------------------------------------


@app.command()
def tap(
    host: str = typer.Option('127.0.0.1', '--host', help='gateway のホスト'),
    port: int = typer.Option(8765, '--port'),
    seconds: float = typer.Option(5.0, '--seconds', '-s', help='何秒つなぐか'),
    stream: list[str] = typer.Option(None, '--stream', help='購読するストリーム'),
    set_param: list[str] = typer.Option(
        None, '--set', help='key=value を送る (param_set の確認用、複数可)'),
    preset: str = typer.Option('', '--apply-preset', help='preset を適用する'),
    verbose: bool = typer.Option(False, '--verbose', '-v', help='1 通ずつ表示'),
) -> None:
    """gateway に繋いでフレームを覗く。

    Phase 2 の受け入れ条件（costmap と pose が JSON で届く）を、ブラウザを
    開かずに確かめる。UI のバグと gateway のバグの切り分けにも使う。

    トークンは環境変数 WHILL_GATEWAY_TOKEN から読む。
    """
    import asyncio

    from whill_cli.tap import TapError, summarize
    from whill_cli.tap import tap as run_tap

    token = os.environ.get('WHILL_GATEWAY_TOKEN', '')
    if not token:
        console.print('[red]WHILL_GATEWAY_TOKEN が未設定[/red]')
        raise typer.Exit(2)

    url = f'ws://{host}:{port}'
    console.print(f'{url} に {seconds:.0f} 秒つなぐ')

    outgoing = []
    for entry in set_param or []:
        if '=' not in entry:
            console.print(f'[red]--set は key=value の形で指定すること: {entry}[/red]')
            raise typer.Exit(2)
        key, _, raw = entry.partition('=')
        outgoing.append({'type': 'param_set', 'key': key, 'value': _parse_value(raw)})
    if preset:
        outgoing.append({'type': 'preset_apply', 'name': preset})

    try:
        counts = asyncio.run(run_tap(
            url, token, seconds=seconds, streams=list(stream) if stream else None,
            send=outgoing or None,
            on_frame=(lambda f: console.print(summarize(f))) if verbose else None))
    except TapError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(1) from None

    table = Table(title=f'{seconds:.0f} 秒間に届いたフレーム')
    table.add_column('type')
    table.add_column('件数', justify='right')
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        table.add_row(kind, str(count))
    console.print(table)

    if not counts:
        console.print('[red]1 通も届かなかった[/red]')
        raise typer.Exit(1)


def _parse_value(raw: str):
    """`--set` の値を JSON として読む。読めなければ文字列のまま。

    `0.5` / `true` / `[0.3, 0.0, 1.0]` を意図どおり送れるようにするため。
    """
    import json as _json
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        return raw


@app.command('manual')
def manual_drive(
    host: str = typer.Option('127.0.0.1', '--host'),
    port: int = typer.Option(8765, '--port'),
    vx: float = typer.Option(0.2, '--vx', help='前進速度 m/s'),
    wz: float = typer.Option(0.0, '--wz', help='旋回速度 rad/s'),
    seconds: float = typer.Option(3.0, '--seconds', '-s', help='何秒指令を出すか'),
    then_silent: float = typer.Option(
        0.0, '--then-silent',
        help='指令を止めてから何秒つないだままにするか（ハートビート断の確認用）'),
    estop: bool = typer.Option(False, '--estop', help='最後に E-stop を送る'),
) -> None:
    """手動速度指令を出す（ハートビート付き）。

    ハートビート断で速度がゼロになることを実機/mock で確かめるための道具。
    `--then-silent` で「指令を止めたまま接続だけ維持する」状況を作れる。

    別ターミナルで `ros2 topic echo /cmd_vel_teleop` を見ること。
    """
    import asyncio

    from whill_cli.tap import TapError
    from whill_cli.tap import manual as run_manual

    token = os.environ.get('WHILL_GATEWAY_TOKEN', '')
    if not token:
        console.print('[red]WHILL_GATEWAY_TOKEN が未設定[/red]')
        raise typer.Exit(2)

    console.print(f'vx={vx} wz={wz} を {seconds:.1f} 秒、'
                  f'その後 {then_silent:.1f} 秒沈黙'
                  + ('、最後に E-stop' if estop else ''))
    try:
        asyncio.run(run_manual(
            f'ws://{host}:{port}', token, vx=vx, wz=wz,
            seconds=seconds, then_silent=then_silent, estop=estop))
    except TapError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(1) from None
    console.print('[green]完了[/green]')


# ---- params ----------------------------------------------------------------


@params_app.command('list')
def params_list(
    robot: str = typer.Option('cr2-01', '--robot', '-r'),
    live: bool = typer.Option(False, '--live', help='live 変更可能なものだけ'),
    node: str = typer.Option('', '--node', '-n', help='ノード名で絞る'),
) -> None:
    """registry のパラメータ一覧。"""
    reg = config.require_registry()
    try:
        registry = reg.load(robot)
    except reg.RegistryError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(2) from None

    table = Table(title=f'{robot} のパラメータ' + (' (live のみ)' if live else ''))
    table.add_column('node')
    table.add_column('name')
    table.add_column('value', justify='right')
    table.add_column('unit')
    table.add_column('live')
    table.add_column('safety')

    count = 0
    for key in sorted(registry.specs):
        spec = registry.specs[key]
        if live and not spec.live:
            continue
        if node and spec.node != node:
            continue
        colour = {'none': 'white', 'caution': 'yellow',
                  'locked_while_moving': 'red'}[spec.safety_class]
        table.add_row(spec.node, spec.name, str(registry.values[key]),
                      spec.unit or '-', 'yes' if spec.live else 'restart',
                      f'[{colour}]{spec.safety_class}[/{colour}]')
        count += 1
    console.print(table)
    console.print(f'{count} 件')


@params_app.command('show')
def params_show(key: str, robot: str = typer.Option('cr2-01', '--robot', '-r')) -> None:
    """1 つのパラメータの詳細（説明・範囲・由来）を出す。"""
    reg = config.require_registry()
    registry = reg.load(robot)
    try:
        spec = registry.spec(key)
    except reg.RegistryError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(2) from None

    console.print(f'[bold]{spec.key}[/bold]')
    console.print(f'  値      : {registry.values[key]} (default {spec.default})')
    console.print(f'  型      : {spec.type}')
    console.print(f'  範囲    : {spec.range or "制約なし"}')
    console.print(f'  単位    : {spec.unit or "-"}')
    console.print(f'  live    : {"即時反映" if spec.live else "再起動が必要"}')
    console.print(f'  safety  : {spec.safety_class}')
    console.print(f'  説明    : {spec.description}')


@params_app.command('probe')
def params_probe(
    robot: str = typer.Option('cr2-01', '--robot', '-r'),
    key: str = typer.Option('', '--key', '-k', help='1 つだけ試す'),
) -> None:
    """起動中のスタックに対して live パラメータが即時反映されるか実際に試す。

    `live: true` が実態と合っているかを機械的に確かめる。合っていないものは
    `config/params.yaml` の `live` を直すこと。試した値は元に戻す。
    """
    from whill_cli.probe import probe_all

    reg = config.require_registry()
    try:
        registry = reg.load(robot)
    except reg.RegistryError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(2) from None

    keys = [key] if key else None
    if key and key not in registry.specs:
        console.print(f'[red]未知のパラメータ: {key}[/red]')
        raise typer.Exit(2)

    results = probe_all(registry, _ros_env(), keys)

    table = Table(title=f'{robot} — live パラメータの即時反映')
    table.add_column('key')
    table.add_column('ROS ノード')
    table.add_column('結果')
    failures = []
    for result in results:
        mark = '[green]OK[/green]' if result.ok else '[red]NG[/red]'
        table.add_row(result.key, result.ros_node,
                      mark if result.ok else f'{mark} {result.detail}')
        if not result.ok:
            failures.append(result)
    console.print(table)

    if failures:
        console.print(f'[red]{len(failures)} 件が即時反映されない。'
                      f'config/params.yaml の live を見直すこと[/red]')
        raise typer.Exit(1)
    console.print(f'[green]{len(results)} 件すべて即時反映された[/green]')


@params_app.command('validate')
def params_validate() -> None:
    """config/ 全体をスキーマ検証する。CI とコミット前に走らせる。"""
    from whill_cli.validate import validate_all

    errors = validate_all(config.config_root())
    for error in errors:
        console.print(f'[red]{error}[/red]')
    if errors:
        console.print(f'[red]{len(errors)} 件のエラー[/red]')
        raise typer.Exit(1)
    console.print('[green]config/ は正常[/green]')


# ---- 情報表示 ---------------------------------------------------------------


@app.command('robots')
def list_robots() -> None:
    """登録されている個体の一覧。"""
    table = Table(title='個体')
    table.add_column('robot_id')
    table.add_column('display_name')
    table.add_column('domain_id', justify='right')
    table.add_column('採寸済み TF', justify='right')
    for robot_id in config.known_robots():
        data = config.robot_config(robot_id)
        tf = data.get('tf_static') or {}
        measured = sum(1 for entry in tf.values() if entry.get('measured'))
        table.add_row(robot_id, str(data.get('display_name', '-')),
                      str(data.get('ros_domain_id', '-')),
                      f'{measured}/{len(tf)}')
    console.print(table)


@app.command('topics')
def list_topics(
    robot: str = typer.Option('cr2-01', '--robot', '-r'),
    mode: str = typer.Option('mock', '--mode', '-m'),
    camera: bool = typer.Option(False, '--camera'),
) -> None:
    """そのモードで出るはずのトピックを宣言から出す（起動せずに確認する用）。"""
    for topic in config.declared_topics(robot, mode, include_camera=camera):
        console.print(topic)


# ---- stack (stackd への薄いクライアント) ------------------------------------


@stack_app.command('status')
def stack_status(url: str = typer.Option('http://127.0.0.1:8770', '--url')) -> None:
    """stackd に現在の状態を問い合わせる。"""
    _stackd_note(url)


@stack_app.command('start')
def stack_start(url: str = typer.Option('http://127.0.0.1:8770', '--url')) -> None:
    """stackd 経由で起動する。"""
    _stackd_note(url)


@stack_app.command('stop')
def stack_stop(url: str = typer.Option('http://127.0.0.1:8770', '--url')) -> None:
    """stackd 経由で停止する。"""
    _stackd_note(url)


def _stackd_note(url: str) -> None:
    console.print(f'[yellow]stackd ({url}) は Phase 2 のスコープ。'
                  f'いまは `whill run` を直接使うこと[/yellow]')
    raise typer.Exit(3)


def main() -> None:
    app()


if __name__ == '__main__':
    sys.exit(app())
