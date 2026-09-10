import os
from glob import glob

from setuptools import setup

package_name = 'whill_bringup'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        # .pgm も含める。map_server は yaml が指す画像を同じディレクトリから読む
        (os.path.join('share', package_name, 'config'),
         glob('config/*.yaml') + glob('config/*.pgm')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='systemlab',
    maintainer_email='ygnk0805@outlook.jp',
    description='real / sim / replay / mock の 4 モードを起動する launch',
    license='BSD-3-Clause',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
