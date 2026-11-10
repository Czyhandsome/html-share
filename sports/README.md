# 赛事数据驱动发布

Python 3.11+，标准库即可构建JSON；YAML需安装 `PyYAML==6.0.3`，流水线已包含该依赖。源文件在 `sports/data/`；生成器输出独立、可离线阅读的HTML。不要手改生成页面。

```sh
python -m unittest discover -s sports/tests -v
python sports/build.py
python sports/build.py --check
```

## 更新与新增

1. 修改赛事JSON或YAML中的比赛和来源，或复制 `sports/core/examples/` 的数据作为新赛事record的data字段。
2. record 使用 `kind: bracket-v1`，给出唯一 `id`、`docs/` 内的 `output` 路径。`event` 声明显示时区、场馆时区和带时区的 `snapshot_at`。
3. 比赛使用稳定id，slots通过entry、winner或group_rank引用，不能手写已知下轮胜者。已开赛结果必须带result_for绑定双方ID；比分由games计算。来源verification必须官方或至少两个独立来源家族。
4. 每轮选择自己的rules：乒乓球BO5/BO7、羽毛球BO3/21分上限30等不同规则不得混用。伤退尚未结束局放in_progress_game，不计入完整games。
5. 小组赛可配置wins或wins/game_ratio/point_ratio；不能解释的同分、退赛、弃权排名必须人工录入官方adjudication。程序不替代项目规程。
6. 本地测试并构建。合入 `main` 后，即使只提交赛事数据，GitHub Actions 也会重新生成赛事页和索引并发布。仓库 HTML 可作为离线快照，线上版本以 Actions 发布产物为准。

新记录示意：
```json
{"schema_version":1,"kind":"bracket-v1","id":"my-event","output":"docs/2026/11/my-event/index.html","notices":[],"data":{"schema_version":1,"event":{},"entries":[],"sources":[],"rules":{},"matches":[]}}
```
完整可运行DSL见core/examples，字段规则见core/schema.json、core/bracketkit.py。新增数据文件会自动加入赛事索引，省略 `back_link` 时自动返回索引。构建器会拒绝丢失或越出 `docs/` 的路径。

在记录顶层填写 `event_dates` 后，索引会显示 `start` 至 `end` 的赛事日期，并按开赛日降序排列。日期格式为 `YYYY-MM-DD`。同一赛事的多份快照可填 `snapshot`，用于区分展示和排序。未填赛事日期的记录排在最后。

## 签表页面

所有 `bracket-v1` 赛事共用一套单页模板。比赛的 `draw` 和 `round` 决定项目和列，`slots` 的 `winner` 引用生成晋级连线。待定签位按轮次展示，填入明确的晋级引用后才会连线。有小组赛时，`groups` 生成积分榜，淘汰赛使用 `group_rank` 引用出线名次。模板沿用原 WTT 页的项目切换、路线高亮和单场详情。

## 迁移边界

WTT的旧比分、逐局与已知对阵原样迁入。`inherited_evidence`明确区分旧记录与本次重新核验；它不是官方证明。迁移锁防止静默改变继承记录。修订继承赛果时去掉该场的继承标记，提供核验来源和时间。首次补齐锁定的未核验比赛时，另在 `migration_releases` 记录依据，并检查整条晋级路线。

S16含瑞士轮，不能冒充纯小组循环赛；使用worlds-swiss适配器保持其页面原布局与语义。7月历史世界杯预测和双打快照通过archive适配器保留其内容，明确不是当前实时赛事。静态内容也录入JSON的content字段，模板仅维护布局。

## 发布

`.github/workflows/sports-pages.yml` 测试→生成→上传Pages→部署；PR只校验不部署。工作流contents只读，部署任务仅pages写与OIDC令牌权限。无需个人访问令牌、不回写main、不改站点根首页。GitHub仓库Settings → Pages → Source应为GitHub Actions；若仍是分支部署，需要仓库管理员切换，不能把代码已提交说成公开页已上线。

## 核验范围

单测验证计分、结果绑定、晋级引用、重复ID、循环、跨项目引用、时区、过期待定阻塞、来源数量、特殊赛况、小组排名、转义、可见卡片和嵌入模型。事实来源的真实性和独立性仍须人工或外部核验。没有来源时保留待定和明确阻塞，不能猜赛果。
