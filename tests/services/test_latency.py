"""所要時間の集計のテスト。

実測そのものは起動中のスタックが要るが、集計と内訳の計算は純粋なので
ここで固める。**内訳が壊れると「200 ms を超えたがどこが遅いか分からない」**
という、計測の意味が無い状態になる。
"""

from __future__ import annotations

from whill_cli.latency import Sample, summarize


def make(key: str, total: float, gateway: float, validate: float,
         service: float) -> Sample:
    return Sample(key=key, accepted=True, total_ms=total, gateway_ms=gateway,
                  validate_ms=validate, service_ms=service)


def test_network_is_total_minus_gateway():
    """往復のうち gateway の外がネットワーク。"""
    assert make('a', 50.0, 20.0, 1.0, 19.0).network_ms == 30.0


def test_network_never_goes_negative():
    """gateway とクライアントで計測の粒度が違う。極小の往復では誤差で負に振れる。

    負の数字を出すと「計測が壊れている」と読まれ、本当に見たい
    「どこが遅いか」から目が逸れる。
    """
    assert make('a', 1.0, 1.4, 0.01, 1.2).network_ms == 0.0


def test_summarize_reports_median_and_max():
    """平均ではなく中央値と最大。

    平均は 1 回の外れ値で歪むし、受け入れ条件として意味があるのは
    「最悪でも 200 ms か」のほう。
    """
    samples = [
        make('a', 1.0, 0.5, 0.01, 0.4),
        make('a', 2.0, 0.6, 0.01, 0.5),
        make('a', 100.0, 0.7, 0.01, 0.6),
    ]
    stats = summarize(samples)['a']
    assert stats['n'] == 3
    assert stats['total_median'] == 2.0
    assert stats['total_max'] == 100.0


def test_summarize_separates_keys():
    """ノードによって応答時間が違う可能性があるので、キーごとに見る。"""
    stats = summarize([
        make('a', 1.0, 0.5, 0.01, 0.4),
        make('b', 9.0, 0.5, 0.01, 0.4),
    ])
    assert set(stats) == {'a', 'b'}
    assert stats['b']['total_max'] == 9.0


def test_varied_values_differ_between_repeats():
    """毎回同じ値を送ると早期に返される可能性がある。"""
    from whill_cli.latency import _vary

    assert _vary(0.6, 0) != _vary(0.6, 1)


def test_vary_leaves_non_numeric_alone():
    from whill_cli.latency import _vary

    assert _vary('text', 3) == 'text'
    assert _vary(True, 3) is True
