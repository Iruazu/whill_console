# ADR-0001: 設定の単一ソースを config/ の yaml に置く

- 状態: 採択
- 日付: 2026-09-10
- Phase: 0

## 背景

既存 `whill_lab0_ros2` では、Nav2 の設定は `nav2_params.yaml` に、センサ位置は
launch 内の `static_transform_publisher` 引数と xacro に、ドライバのポートや IP は
launch のデフォルト値に散っていた。1 台のうちは回るが、同型 3 台に増やすと
「どれが個体差でどれが共通か」が読み取れなくなる。

さらに Web コンソールがスライダーを自動生成するには、各パラメータの範囲・単位・
走行中に変えてよいかを機械可読な形で持つ必要がある。ROS の
`ParameterDescriptor` はノードが起動していないと読めないので、それ単体では
「起動前に UI を組む」ことができない。

## 決定

設定の一次情報を `config/` の yaml に置き、優先度を次のとおり固定する。

```
config/params.yaml  <  config/robots/cr2-0N.yaml  <  config/presets/*.yaml  <  スライダー
```

- `params.yaml` は 3 台共通。各エントリが `node / name / type / default / range /
  unit / live / safety_class / description` を持つ。
- `robots/cr2-base.yaml` はドライバとモードの宣言。どのドライバが何を publish するかの契約。
- `robots/cr2-0N.yaml` は個体差のみ（ポート、IP、TF、domain_id、閾値上書き）。
- `presets/*.yaml` はスライダープリセット。
- スライダーの一時変更は永続化しない。gateway がメモリに持ち、変更ログだけ
  `/whill/param_changes` に流して MCAP に残す。

ROS ノードは `whill_params.descriptors.declare_from_registry` を通してのみ
パラメータを宣言する。手で `declare_parameter` を書かない。

## 帰結

**得たもの**

- UI がノード起動前にスライダーを組める（`whill params list` が同じ情報を CLI で出す）。
- 「走行中に変えてよいか」が `safety_class` として 1 か所に書かれ、gateway が
  機械的に拒否できる。人の記憶に頼らない。
- 値の由来（なぜ 0.6 なのか）が `description` に残り、UI のツールチップに出る。
  実測チューニングの理由が消えない。
- 個体差が 1 ファイルに閉じるので、3 台目を足すのは yaml を 1 枚書くだけになる。

**払ったもの**

- Nav2 の設定が二重管理になりうる。これを避けるため、生成は既存 `nav2_params.yaml`
  をテンプレートとして「registry が管理するキーだけ差し替える」方式にした。
  registry に載せる価値のない定型（plugin 名の羅列、BT の xml パス）は
  テンプレート側に残す。Phase 1 で「既定値のみなら差分ゼロ」を pytest で担保する。
- `config/` を colcon の外に置いたため、ROS パッケージから参照する経路が必要になった。
  `WHILL_PLATFORM_CONFIG` を最優先し、無ければリポジトリを遡り、最後に
  ament の share に複製したものを見る。share を最後にするのは、リポジトリを
  編集したのに古い値が読まれる事故を避けるため。

## 追記（Phase 4）: 構造は registry に載せない

仮想障害物の層を足すとき、costmap の `plugins` をどう扱うかで迷った。

`plugins` は**構造**であって「人が触る値」ではない。registry に載せると、
Nav2 の層構成の全部を registry で二重管理することになる。かといって
テンプレート（`whill_lab0_ros2` の `nav2_params.yaml`）は他リポなので編集できない。

**registry が持つのは on/off の bool だけにし、どこに挿すかは生成側が決める**
という形にした:

```yaml
# config/params.yaml
- node: global_costmap
  name: virtual_obstacles_enabled
  type: bool
  live: false          # 層の追加は構造の変更なので再起動が要る
```

生成側（`generate_nav2_params._insert_virtual_obstacles`）が `plugins` の
`inflation_layer` の直前に挿し、層のパラメータ塊を作る。挿す位置に意味がある
（後ろだと膨張がかからず、車体が入れない隙間を通る経路が出る）ので、
これは人が毎回指定するものではなく、コードで保証すべきこと。

この結果、Phase 1 の「既定値のみで差分ゼロ」は**層を切った状態**で担保する
ことになった。層の追加は意図した差分で、それ以外の変更が紛れ込んでいない
ことを `test_the_only_difference_is_the_virtual_obstacles_layer` が見る。

## 検討して捨てた案

- **ROS パラメータだけで完結させる**: ノードが起動していないと読めない。
  UI を先に組めず、モード切替のたびに全ノードを上げ直す必要が出る。
- **`params.yaml` から Nav2 params を全文生成する**: Nav2 の定型部分まで
  registry に載せることになり、上流の Nav2 が変わるたびに追随が要る。
  「人が触る値」だけを持つほうが保守量が小さい。
- **個体差を環境変数で渡す**: 3 台ぶんの起動手順が shell 履歴に散る。
  yaml に書けば `whill robots` で一覧でき、TF の採寸状況も一緒に持てる。
