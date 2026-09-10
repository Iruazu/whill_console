import os
from glob import glob

from setuptools import setup

package_name = 'whill_params'

# config/ はリポジトリ直下 (../../../config) への symlink。colcon は data_files に
# 絶対パスやパッケージ外のパスを許さないため、symlink 経由で相対パスにしている。
# 実行時は WHILL_PLATFORM_CONFIG が指す元ファイルを優先し、share の複製は fallback。


def config_data_files():
    entries = []
    for sub in ('', 'robots', 'presets'):
        pattern = os.path.join('config', sub, '*.yaml') if sub \
            else os.path.join('config', '*.yaml')
        files = sorted(f for f in glob(pattern) if os.path.isfile(f))
        if files:
            dest = os.path.join('share', package_name, 'config', sub) if sub \
                else os.path.join('share', package_name, 'config')
            entries.append((dest, files))
    return entries


setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ] + config_data_files(),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='systemlab',
    maintainer_email='ygnk0805@outlook.jp',
    description='config/ の yaml を単一ソースとして読み、registry と Nav2 params 生成を提供する',
    license='BSD-3-Clause',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'generate_nav2_params = whill_params.generate_nav2_params:main',
        ],
    },
)
