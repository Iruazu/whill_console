// UI で置いた仮想障害物を Nav2 の costmap に注入する層。
//
// 狙いは「実機を走らせずに、この配置で経路がどう変わるかを試せること」。
// 実機で幽霊障害物を置いて確かめるのは最後の一手であって、最初の一手ではない。
//
// ## 全量置換にしている理由
//
// `/whill/virtual_obstacles` は毎回すべての障害物を載せて来る。差分にすると、
// UI と costmap の状態がずれたときに復旧できない（どちらが正しいか分からず、
// 片方を消しても消えない障害物が残る）。数は高々数十なので毎回全部でよい。
//
// ## inflation より前に置くこと
//
// `plugins` の並びで `inflation_layer` より後ろに置くと膨張がかからず、
// 車体が入れない隙間を通る経路が出る。生成側（whill_params）が並びを
// 保証している。

#ifndef WHILL_COSTMAP_PLUGINS__VIRTUAL_OBSTACLES_LAYER_HPP_
#define WHILL_COSTMAP_PLUGINS__VIRTUAL_OBSTACLES_LAYER_HPP_

#include <mutex>
#include <string>
#include <vector>

#include "nav2_costmap_2d/costmap_layer.hpp"
#include "nav2_costmap_2d/layer.hpp"
#include "rclcpp/rclcpp.hpp"
#include "whill_msgs/msg/virtual_obstacle_array.hpp"

namespace whill_costmap_plugins
{

/// 1 個ぶんの円。world 座標 (m)。
struct Circle
{
  double x;
  double y;
  double radius;
};

class VirtualObstaclesLayer : public nav2_costmap_2d::Layer
{
public:
  VirtualObstaclesLayer() = default;

  void onInitialize() override;

  void updateBounds(
    double robot_x, double robot_y, double robot_yaw,
    double * min_x, double * min_y, double * max_x, double * max_y) override;

  void updateCosts(
    nav2_costmap_2d::Costmap2D & master_grid,
    int min_i, int min_j, int max_i, int max_j) override;

  void reset() override;

  // 「クリア可能な層か」。仮想障害物は人が明示的に置いたものなので、
  // Nav2 のリカバリ（costmap のクリア）で勝手に消してはいけない。
  // 消えると「置いたはずの障害物が無くなった」ことに気づけない。
  bool isClearable() override {return false;}

private:
  void onObstacles(const whill_msgs::msg::VirtualObstacleArray::SharedPtr message);

  rclcpp::Subscription<whill_msgs::msg::VirtualObstacleArray>::SharedPtr subscription_;

  // 購読は executor のスレッド、updateCosts は costmap のスレッドから
  // 呼ばれる。両方が触るのでロックする。
  std::mutex mutex_;
  std::vector<Circle> obstacles_;

  // 前回書き込んだ範囲。障害物を消したときに、その範囲を更新対象に
  // 含めないと消えた跡が残る。
  double last_min_x_ {0.0};
  double last_min_y_ {0.0};
  double last_max_x_ {0.0};
  double last_max_y_ {0.0};
  bool has_last_bounds_ {false};

  std::string topic_;
  double max_radius_ {5.0};
};

}  // namespace whill_costmap_plugins

#endif  // WHILL_COSTMAP_PLUGINS__VIRTUAL_OBSTACLES_LAYER_HPP_
