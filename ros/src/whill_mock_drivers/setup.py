import os
from glob import glob

from setuptools import setup

package_name = 'whill_mock_drivers'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='systemlab',
    maintainer_email='ygnk0805@outlook.jp',
    description='実機なしで開発するためのモックドライバ',
    license='BSD-3-Clause',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'mock_whill_serial = whill_mock_drivers.mock_whill_serial:main',
            'mock_velodyne = whill_mock_drivers.mock_velodyne:main',
            'mock_bno085 = whill_mock_drivers.mock_bno085:main',
            'mock_realsense = whill_mock_drivers.mock_realsense:main',
        ],
    },
)
