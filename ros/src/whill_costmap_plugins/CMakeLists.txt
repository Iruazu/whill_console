cmake_minimum_required(VERSION 3.8)
project(whill_costmap_plugins)

# Phase 4 (仮想障害物 layer) で中身を入れる。Phase 0 の時点では、
# 依存解決とビルド経路だけ通しておく空パッケージ。空のまま残す期間を
# 短くするため、Phase 4 の issue から必ずこのファイルを開くこと。

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(nav2_costmap_2d REQUIRED)
find_package(pluginlib REQUIRED)
find_package(whill_msgs REQUIRED)

install(DIRECTORY include/ DESTINATION include)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
