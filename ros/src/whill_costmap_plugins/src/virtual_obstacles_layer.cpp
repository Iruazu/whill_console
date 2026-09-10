#include "whill_costmap_plugins/virtual_obstacles_layer.hpp"

#include <algorithm>
#include <cmath>
#include <memory>

#include "nav2_costmap_2d/costmap_math.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace whill_costmap_plugins
{

void VirtualObstaclesLayer::onInitialize()
{
  auto node = node_.lock();
  if (!node) {
    throw std::runtime_error{"VirtualObstaclesLayer: ノードを取得できない"};
  }

  declareParameter("enabled", rclcpp::ParameterValue(true));
  declareParameter("topic", rclcpp::ParameterValue(std::string{"/whill/virtual_obstacles"}));
  // 巨大な円を置かれると costmap が埋まる。UI 側でも制限するが、
  // WebSocket には任意の JSON を投げられるので最終的にここでも見る。
  declareParameter("max_radius", rclcpp::ParameterValue(5.0));

  node->get_parameter(name_ + "." + "enabled", enabled_);
  node->get_parameter(name_ + "." + "topic", topic_);
  node->get_parameter(name_ + "." + "max_radius", max_radius_);

  current_ = true;

  // 全量置換なので、直近の 1 通だけ持てばよい。transient_local にするのは
  // gateway より後に costmap が立ち上がったときに取りこぼさないため。
  rclcpp::QoS qos{rclcpp::KeepLast(1)};
  qos.reliable().transient_local();

  subscription_ = node->create_subscription<whill_msgs::msg::VirtualObstacleArray>(
    topic_, qos,
    std::bind(&VirtualObstaclesLayer::onObstacles, this, std::placeholders::_1));

  RCLCPP_INFO(
    node->get_logger(),
    "VirtualObstaclesLayer: %s を購読 (max_radius=%.2f m)", topic_.c_str(), max_radius_);
}

void VirtualObstaclesLayer::onObstacles(
  const whill_msgs::msg::VirtualObstacleArray::SharedPtr message)
{
  std::vector<Circle> next;
  next.reserve(message->obstacles.size());

  auto node = node_.lock();
  for (const auto & obstacle : message->obstacles) {
    if (!std::isfinite(obstacle.center.x) || !std::isfinite(obstacle.center.y) ||
      !std::isfinite(obstacle.radius))
    {
      // NaN を通すと costmap の全域が塗られたり無限ループになる。
      // 黙って捨てず、なぜ効かないのかが分かるようにする。
      if (node) {
        RCLCPP_WARN(
          node->get_logger(),
          "VirtualObstaclesLayer: 有限でない値の障害物を捨てた (id=%s)",
          obstacle.id.c_str());
      }
      continue;
    }
    if (obstacle.radius <= 0.0) {
      continue;
    }
    const double radius = std::min(static_cast<double>(obstacle.radius), max_radius_);
    if (node && radius < obstacle.radius) {
      RCLCPP_WARN(
        node->get_logger(),
        "VirtualObstaclesLayer: 半径 %.2f m を上限 %.2f m に丸めた (id=%s)",
        obstacle.radius, max_radius_, obstacle.id.c_str());
    }
    next.push_back(Circle{obstacle.center.x, obstacle.center.y, radius});
  }

  std::lock_guard<std::mutex> lock{mutex_};
  obstacles_ = std::move(next);
  // 中身が変わったので次回の更新で塗り直す。
  current_ = false;
}

void VirtualObstaclesLayer::updateBounds(
  double /*robot_x*/, double /*robot_y*/, double /*robot_yaw*/,
  double * min_x, double * min_y, double * max_x, double * max_y)
{
  if (!enabled_) {
    return;
  }

  std::lock_guard<std::mutex> lock{mutex_};

  // 前回書いた範囲を必ず含める。含めないと、障害物を消したときに
  // その跡が costmap に残り続ける（消したのに経路が迂回したまま）。
  if (has_last_bounds_) {
    *min_x = std::min(*min_x, last_min_x_);
    *min_y = std::min(*min_y, last_min_y_);
    *max_x = std::max(*max_x, last_max_x_);
    *max_y = std::max(*max_y, last_max_y_);
  }

  if (obstacles_.empty()) {
    has_last_bounds_ = false;
    current_ = true;
    return;
  }

  double lo_x = std::numeric_limits<double>::max();
  double lo_y = std::numeric_limits<double>::max();
  double hi_x = std::numeric_limits<double>::lowest();
  double hi_y = std::numeric_limits<double>::lowest();

  for (const auto & circle : obstacles_) {
    lo_x = std::min(lo_x, circle.x - circle.radius);
    lo_y = std::min(lo_y, circle.y - circle.radius);
    hi_x = std::max(hi_x, circle.x + circle.radius);
    hi_y = std::max(hi_y, circle.y + circle.radius);
  }

  *min_x = std::min(*min_x, lo_x);
  *min_y = std::min(*min_y, lo_y);
  *max_x = std::max(*max_x, hi_x);
  *max_y = std::max(*max_y, hi_y);

  last_min_x_ = lo_x;
  last_min_y_ = lo_y;
  last_max_x_ = hi_x;
  last_max_y_ = hi_y;
  has_last_bounds_ = true;
  current_ = true;
}

void VirtualObstaclesLayer::updateCosts(
  nav2_costmap_2d::Costmap2D & master_grid,
  int min_i, int min_j, int max_i, int max_j)
{
  if (!enabled_) {
    return;
  }

  std::vector<Circle> snapshot;
  {
    std::lock_guard<std::mutex> lock{mutex_};
    snapshot = obstacles_;
  }
  if (snapshot.empty()) {
    return;
  }

  const double resolution = master_grid.getResolution();

  for (const auto & circle : snapshot) {
    // 円の外接矩形だけを走査する。costmap 全域を舐めると 200x200 でも
    // 更新のたびに 4 万セルを見ることになる。
    unsigned int lo_i = 0;
    unsigned int lo_j = 0;
    unsigned int hi_i = 0;
    unsigned int hi_j = 0;
    if (!master_grid.worldToMap(circle.x - circle.radius, circle.y - circle.radius, lo_i, lo_j)) {
      // 左下が地図の外。地図に重なる部分だけ塗りたいので、範囲で丸める。
      lo_i = static_cast<unsigned int>(std::max(min_i, 0));
      lo_j = static_cast<unsigned int>(std::max(min_j, 0));
    }
    if (!master_grid.worldToMap(circle.x + circle.radius, circle.y + circle.radius, hi_i, hi_j)) {
      hi_i = static_cast<unsigned int>(std::max(max_i - 1, 0));
      hi_j = static_cast<unsigned int>(std::max(max_j - 1, 0));
    }

    const int start_i = std::max(static_cast<int>(lo_i), min_i);
    const int start_j = std::max(static_cast<int>(lo_j), min_j);
    const int end_i = std::min(static_cast<int>(hi_i) + 1, max_i);
    const int end_j = std::min(static_cast<int>(hi_j) + 1, max_j);

    const double radius_sq = circle.radius * circle.radius;

    for (int j = start_j; j < end_j; ++j) {
      for (int i = start_i; i < end_i; ++i) {
        double wx = 0.0;
        double wy = 0.0;
        master_grid.mapToWorld(
          static_cast<unsigned int>(i), static_cast<unsigned int>(j), wx, wy);
        const double dx = wx - circle.x;
        const double dy = wy - circle.y;
        if (dx * dx + dy * dy > radius_sq) {
          continue;
        }
        // 上書きではなく最大値。他の層が置いた障害物を消さない。
        // （静的地図の壁を「仮想障害物が無いから空き」にしてはいけない）
        master_grid.setCost(
          static_cast<unsigned int>(i), static_cast<unsigned int>(j),
          nav2_costmap_2d::LETHAL_OBSTACLE);
      }
    }
    (void)resolution;
  }
}

void VirtualObstaclesLayer::reset()
{
  // ここでは障害物を消さない。`isClearable()` が false なのと同じ理由で、
  // 人が明示的に置いたものを Nav2 のリカバリで勝手に消さない。
  // 消すのは UI からの全量置換（空配列）だけ。
  std::lock_guard<std::mutex> lock{mutex_};
  current_ = false;
}

}  // namespace whill_costmap_plugins

PLUGINLIB_EXPORT_CLASS(whill_costmap_plugins::VirtualObstaclesLayer, nav2_costmap_2d::Layer)
