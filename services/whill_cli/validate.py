"""config/ の JSON Schema 検証。

スキーマ本体は config/schema/*.json に置かず、ここにコードとして持つ。
理由は、スキーマと registry のパース実装がずれると「検証は通るが読めない」
状態が起きるため。1 か所に寄せて、registry の要求とスキーマを同時に直す。

Phase 1 でここを CI に載せる。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SAFETY_CLASSES = ['none', 'caution', 'locked_while_moving']
PARAM_TYPES = ['double', 'int', 'bool', 'string', 'double_array']

PARAMS_SCHEMA: dict[str, Any] = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'required': ['schema_version', 'params'],
    'properties': {
        'schema_version': {'const': 1},
        'params': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'allOf': [{
                    'if': {'properties': {'type': {'const': 'double_array'}}},
                    'then': {'required': ['elements']},
                }],
                'required': ['node', 'name', 'type', 'default', 'live',
                             'safety_class', 'description'],
                'additionalProperties': False,
                'properties': {
                    'node': {'type': 'string', 'minLength': 1},
                    'name': {'type': 'string', 'minLength': 1},
                    'type': {'enum': PARAM_TYPES},
                    'default': {},
                    'range': {
                        'oneOf': [
                            {'type': 'null'},
                            {
                                'type': 'object',
                                'additionalProperties': False,
                                'properties': {
                                    'min': {'type': 'number'},
                                    'max': {'type': 'number'},
                                    'step': {'type': 'number', 'exclusiveMinimum': 0},
                                },
                            },
                        ]
                    },
                    # double_array 用。軸ごとに意味と範囲が違うので配列で持つ
                    # ([vx, vy, vyaw] の vy は差動二輪では構造的に 0 固定)。
                    'elements': {
                        'type': 'array',
                        'minItems': 1,
                        'items': {
                            'type': 'object',
                            'required': ['label'],
                            'additionalProperties': False,
                            'properties': {
                                'label': {'type': 'string', 'minLength': 1},
                                'range': {
                                    'type': 'object',
                                    'additionalProperties': False,
                                    'properties': {
                                        'min': {'type': 'number'},
                                        'max': {'type': 'number'},
                                        'step': {'type': 'number', 'exclusiveMinimum': 0},
                                    },
                                },
                            },
                        },
                    },
                    'unit': {'type': ['string', 'null']},
                    'live': {'type': 'boolean'},
                    'safety_class': {'enum': SAFETY_CLASSES},
                    # 説明が空だと UI のツールチップが空になる。原則 6 の実効性が
                    # 落ちるので最低限の長さを要求する。
                    'description': {'type': 'string', 'minLength': 10},
                },
            },
        },
    },
}

TELEMETRY_ITEM = {
    'type': 'object',
    'required': ['name', 'topic', 'field', 'widget'],
    'additionalProperties': False,
    'properties': {
        'name': {'type': 'string', 'minLength': 1},
        'topic': {'type': 'string', 'pattern': '^/'},
        'field': {'type': 'string', 'minLength': 1},
        'unit': {'type': ['string', 'null']},
        'widget': {'enum': ['number', 'bar', 'heading']},
        'warn': {'type': ['number', 'null']},
        'crit': {'type': ['number', 'null']},
        'compare': {'enum': ['above', 'below', 'none']},
        'description': {'type': 'string'},
    },
}

# 派生テレメトリは単一トピックの 1 フィールドではなく複数トピックから計算する。
# topic/field を必須にしたままだと表現できないので別スキーマにする。
DERIVED_TELEMETRY_ITEM = {
    'type': 'object',
    'required': ['name', 'inputs', 'widget'],
    'additionalProperties': False,
    'properties': {
        'name': {'type': 'string', 'minLength': 1},
        'description': {'type': 'string'},
        'inputs': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'pattern': '^/'}},
        'unit': {'type': ['string', 'null']},
        'widget': {'enum': ['number', 'bar', 'heading']},
        'warn': {'type': ['number', 'null']},
        'crit': {'type': ['number', 'null']},
        'compare': {'enum': ['above', 'below', 'none']},
    },
}

BASE_SCHEMA: dict[str, Any] = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'required': ['schema_version', 'drivers', 'modes'],
    'properties': {
        'schema_version': {'const': 1},
        'model': {'type': 'string'},
        'drivers': {
            'type': 'object',
            'minProperties': 1,
            'additionalProperties': {
                'type': 'object',
                'required': ['mock_node', 'publishes'],
                'properties': {
                    'description': {'type': 'string'},
                    'real_package': {'type': 'string'},
                    'mock_node': {'type': 'string', 'minLength': 1},
                    'qos': {'enum': ['sensor_data', 'default']},
                    'enabled_by_default': {'type': 'boolean'},
                    'cold_boot_sequence': {'type': 'array', 'items': {'type': 'string'}},
                    # 実ドライバが LifecycleNode かどうか。real モードの launch が
                    # configure → activate の遷移と待ちを組む必要があるかを決める。
                    'lifecycle': {'type': 'boolean'},
                    'publishes': {
                        'type': 'array',
                        'minItems': 1,
                        'items': {
                            'type': 'object',
                            'required': ['topic', 'type'],
                            'additionalProperties': False,
                            'properties': {
                                'topic': {'type': 'string', 'pattern': '^/'},
                                'type': {'type': 'string', 'pattern': '^[a-z_0-9]+/msg/'},
                                'rate_hz': {'type': 'number', 'exclusiveMinimum': 0},
                            },
                        },
                    },
                    'subscribes': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'required': ['topic', 'type'],
                            'additionalProperties': False,
                            'properties': {
                                'topic': {'type': 'string', 'pattern': '^/'},
                                'type': {'type': 'string', 'pattern': '^[a-z_0-9]+/msg/'},
                            },
                        },
                    },
                    'telemetry': {'type': 'array', 'items': TELEMETRY_ITEM},
                },
            },
        },
        'derived_telemetry': {'type': 'array', 'items': DERIVED_TELEMETRY_ITEM},
        'modes': {
            'type': 'object',
            'minProperties': 1,
            'additionalProperties': {
                'type': 'object',
                'required': ['drivers', 'use_sim_time'],
                'additionalProperties': False,
                'properties': {
                    'description': {'type': 'string'},
                    'drivers': {'type': 'array', 'items': {'type': 'string'}},
                    'include_stack': {'type': 'boolean'},
                    'use_sim_time': {'type': 'boolean'},
                },
            },
        },
    },
}

TF_ENTRY = {
    'type': 'object',
    'required': ['parent', 'xyz', 'rpy', 'measured'],
    'additionalProperties': False,
    'properties': {
        'parent': {'type': 'string', 'minLength': 1},
        'xyz': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
        'rpy': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
        # 採寸済みか推定かを必ず区別させる。推定値を採寸値の顔で置くのが
        # 一番危ないので、省略可能にしない。
        'measured': {'type': 'boolean'},
        'note': {'type': 'string'},
    },
}

ROBOT_SCHEMA: dict[str, Any] = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'required': ['schema_version', 'robot_id', 'ros_domain_id', 'tf_static'],
    'properties': {
        'schema_version': {'const': 1},
        'robot_id': {'type': 'string', 'pattern': '^cr2-[0-9]{2}$'},
        'display_name': {'type': 'string'},
        'model': {'type': 'string'},
        'ros_domain_id': {'type': 'integer', 'minimum': 0, 'maximum': 232},
        'hardware': {'type': 'object'},
        'tf_static': {'type': 'object', 'additionalProperties': TF_ENTRY},
        'telemetry_overrides': {'type': 'object'},
        'param_overrides': {'type': 'object'},
        'maps': {'type': 'object'},
    },
}

PRESET_SCHEMA: dict[str, Any] = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'required': ['schema_version', 'name', 'overrides'],
    'additionalProperties': False,
    'properties': {
        'schema_version': {'const': 1},
        'name': {'type': 'string', 'minLength': 1},
        'description': {'type': 'string'},
        'real_robot_allowed': {'type': 'boolean'},
        'overrides': {'type': 'object', 'minProperties': 1},
    },
}


def _load(path: Path) -> Any:
    with path.open(encoding='utf-8') as handle:
        return yaml.safe_load(handle)


def _check(path: Path, schema: dict[str, Any]) -> list[str]:
    data = _load(path)
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = '.'.join(str(p) for p in error.path) or '(root)'
        errors.append(f'{path.name}: {location}: {error.message}')
    return errors


def validate_all(root: Path) -> list[str]:
    """config/ を丸ごと検証し、エラー文字列のリストを返す。空なら正常。"""
    errors: list[str] = []

    params_path = root / 'params.yaml'
    errors += _check(params_path, PARAMS_SCHEMA)

    base_path = root / 'robots' / 'cr2-base.yaml'
    errors += _check(base_path, BASE_SCHEMA)

    robot_paths = sorted(p for p in (root / 'robots').glob('cr2-*.yaml')
                         if p.stem != 'cr2-base')
    for path in robot_paths:
        errors += _check(path, ROBOT_SCHEMA)

    preset_paths = sorted((root / 'presets').glob('*.yaml'))
    for path in preset_paths:
        errors += _check(path, PRESET_SCHEMA)

    # ---- スキーマ単体では見られない相互参照 ----
    if not errors:
        errors += _cross_checks(_load(params_path), _load(base_path),
                                robot_paths, preset_paths)
    return errors


def _cross_checks(params: dict, base: dict, robot_paths: list[Path],
                  preset_paths: list[Path]) -> list[str]:
    errors: list[str] = []
    keys = {f'{entry["node"]}.{entry["name"]}' for entry in params['params']}

    # preset の overrides が params.yaml に存在すること。typo が静かに
    # 無視されると、プリセットを当てたのに値が変わらない事故になる。
    for path in preset_paths:
        preset = _load(path)
        for key in (preset.get('overrides') or {}):
            if key not in keys:
                errors.append(f'{path.name}: overrides の "{key}" が params.yaml に無い')

    # 個体 yaml の param_overrides も同様
    for path in robot_paths:
        robot = _load(path)
        for key in (robot.get('param_overrides') or {}):
            if key not in keys:
                errors.append(f'{path.name}: param_overrides の "{key}" が params.yaml に無い')

    # modes が参照するドライバが drivers に宣言されていること
    declared = set((base.get('drivers') or {}).keys())
    for mode_name, mode in (base.get('modes') or {}).items():
        for driver in mode.get('drivers') or []:
            if driver not in declared:
                errors.append(
                    f'cr2-base.yaml: modes.{mode_name} が未宣言のドライバ "{driver}" を参照している')

    # トピック名の重複（別ドライバが同じトピックを出す宣言）を弾く
    seen: dict[str, str] = {}
    for driver, declaration in (base.get('drivers') or {}).items():
        for entry in declaration.get('publishes') or []:
            topic = entry['topic']
            if topic in seen:
                errors.append(
                    f'cr2-base.yaml: トピック {topic} を {seen[topic]} と {driver} が'
                    f'二重に publish 宣言している')
            seen[topic] = driver

    return errors
