# 开发与数据流程

面向开发者：本地运行、数据同步与整理的各个步骤。网站介绍见 [README](../README.md)。

线上查询全部走自己的 D1 和静态文件，运行时不请求 Anitabi 的 API；数据由 GitHub Actions 每日同步（`.github/workflows/data-sync.yml`）。

技术栈：[Void](https://void.cloud)（Vite 全栈框架，部署到 Cloudflare Workers）+ Vue + D1 + MapLibre。

## 本地开发

需要 Node.js 24+、pnpm、Python 3.10+。同步只用标准库；导出时生成搜索索引需要 `pip install -r sync/requirements.txt`（OpenCC 做简繁归一、pykakasi 生成罗马音）。

```bash
pnpm install
pnpm void db migrate   # 建表（本地 D1）
pnpm data              # 同步 Anitabi → 导出 → 导入本地 D1
pnpm dev               # http://localhost:5173
```

`pnpm data` 由三步组成，可以单独跑：

| 命令 | 作用 |
|---|---|
| `pnpm data:sync` | `python -m sync.sync`：全量 / 增量同步并规范化到 `data/anitabi.sqlite`，生成质量报告 `data/report.md` |
| `pnpm data:export` | `python -m sync.export`：生成 `data/d1-import.sql`、搜索折叠表 `data/fold.json`、地图点位 `public/data/points.geojson`、作品索引 `public/data/bangumi.json` |
| `pnpm data:import` | 把 `data/d1-import.sql` 全量覆盖导入本地 D1，并重建地标名全文索引 |

`data/` 是生成物，不进 git；`public/data/` 由每日同步提交。

## 数据整理与补全

在同步数据之上再做一层整理和补全，产出**可审核的派生数据**，不覆盖原始数据：

- 派生结果全部写进 `data/enrich.sqlite`，`data/anitabi.sqlite` 只以只读方式挂载，脚本不会改它。
- 每条派生数据都带来源（`source` / `model` / `prompt_version` / `method`）和置信度（`confidence`）。
- 外部请求和 LLM 结果缓存在 `data/cache.sqlite`，重跑只请求新内容；`enrich.sqlite` 删了可以重建，缓存不会丢。
- 每步跑完会刷新 `data/report.md` 末尾的「整理与补全」一节，待复核清单导出到 `data/review/*.csv`。

| 命令 | 作用 | 外部依赖 |
|---|---|---|
| `pnpm enrich:places` | 把坐标重复 / 相近且名称相似的地标合并成地点，生成 `place` / `place_point`（一个地点挂多部作品） | 无，几秒 |
| `pnpm enrich:bgm` | 从 [Bangumi API](https://bangumi.github.io/api/) 补别名、原名、英文 / 罗马音标题、放送日期，生成 `bangumi_meta` / `bangumi_alias` | api.bgm.tv，1 次/秒，全量约 26 分钟 |
| `pnpm enrich:geocheck` | 用国土地理院反向地理编码查地标所属市町村，与作品 `city` 比对，生成 `point_geo` / `review_city` 和复核清单 | GSI，1 次/秒，全量约 1.2 万次请求（可 `--max-requests N` 分批） |
| `pnpm enrich:notes` | 用 Claude 把备注分类成标签（禁止进入、已消失、需购票/预约、季节限定、拍摄礼仪等），顺带识别集数，生成 `note_class` / `note_tag` | Claude API |
| `pnpm enrich:translate` | 给作品标题、地标名、备注补齐 zh-Hans / zh-Hant / ja / en，生成 `translation` 表（见下文） | Claude API、OpenCC |
| `pnpm enrich:cities` | 到 Wikidata 查作品所在城市的简繁日英名称，生成 `city_label` 表 | Wikidata API |
| `pnpm gaps list` / `run` / `apply` | 补漏：Anitabi 没收录、但有实地探访记录的作品（舞台探訪アーカイブ），LLM 从探访文章提取地标草稿，审核后并入 `sync/manual.json`（见 `sync/gaps.py`） | 探访目录与博客、Claude API、OSM Nominatim、国土地理院 |
| `python -m sync.covers` | 把 Bangumi 封面镜像到 R2（cdn.jannchie.com），进度清单存在 R2 上，本机和 CI 共用 | Bangumi API、R2 |
| `python -m sync.tracemoe extract <dump>` | 从 [trace.moe 数据库 dump](https://huggingface.co/datasets/soruly/trace.moe-database-dump) 抽出补漏相关作品的逐帧向量，供 `pnpm gaps trace` 在本地核对截图的集数与时间 | 本机 zstd |
| `pnpm enrich:report` | 只根据现有结果重新生成报告 | 无 |
| `pnpm enrich` | 依次跑不花钱的三步：places → bgm → geocheck | |

数据目录默认是 `<项目根>/data`，可用环境变量 `JUNREI_DATA` 或 `--data` 指定（例如在 git worktree 里复用主仓库的数据）。

两个 LLM 步骤需要 `pip install anthropic` 和 Claude API 凭据（`ANTHROPIC_API_KEY` 等，按 SDK 默认顺序解析），默认模型 `claude-haiku-5-5`（短文本分类和翻译够用，批量价约 $0.05 / $0.25 每百万 token；要更稳可 `--model claude-sonnet-5-5`）：

```bash
pnpm enrich:notes --dry-run          # 不调用 API：看去重后要发多少请求、请求长什么样
pnpm enrich:notes --mode sync --limit 200   # 同步小规模试跑，先抽查结果
pnpm enrich:notes --wait             # 全量走 Message Batches（半价、异步），等待结果
```

- 相同文本只请求一次，结果按 `(任务, 提示词版本, 模型, 文本哈希)` 缓存；改了提示词，版本号里的哈希会变，旧缓存自动不再使用。
- 不加 `--wait` 时提交完批次就退出，批次 id 记在缓存库里，下次运行会先收取结果。
- 同步模式下，支持的模型（Opus / Sonnet 5.5 / Fable）会开启服务端 refusal fallback，Haiku 不支持；Batches 不支持该参数。
- 标签和置信度是模型给的，机翻名称前端展示时应标明「机翻」，人工录入的中文名永远优先。

多语言翻译表 `translation(entity, entity_id, field, lang, text, source, machine_translated, confidence, …)`：

- `entity` / `field`：`bangumi.title`、`point.name`、`point.mark`；`entity_id` 是作品 id 或 `作品id:地标id`。
- `source` 区分来源，同一语言可以有多行，前端按 `anitabi > bangumi > llm > opencc` 取：
  `anitabi`（原文；`point.name` 的语言由模型判断，没有模型结果时按文字猜，`confidence` 是语言判断的把握）、
  `bangumi`（Bangumi API 的原名 / 中文名 / 英文名，罗马音记为 `ja-Latn`，需先跑 `enrich:bgm`）、
  `llm`（只补没有人工数据的语言）、`opencc`（繁体由最优先的简体按 OpenCC `s2t` 规则转换，`derived_from` 记录转换自哪行）。
- 作品标题只对 Anitabi + Bangumi 仍缺语言的作品调用 LLM；地标名和备注全部过 LLM。`--fields name,mark,title` 选择要跑的部分，`--fields ""` 只整理已有数据和繁体转换。
- 作品标题建议用 `--field-model title=claude-sonnet-5-5`：Haiku 常把官方英文名编错；Sonnet 拿不准时会给低置信度（<0.5），前端可据此不展示。
- 繁体转换需要 `pip install opencc-python-reimplemented`（或 `opencc`），没装会跳过。

如果 Python 访问 `api.bgm.tv` 报 `certificate has expired`（部分 Windows 的系统证书库问题），`pip install certifi` 后脚本会自动改用它的根证书，或用环境变量 `SSL_CERT_FILE` 指定证书文件。

外部数据源只用官方开放接口（Bangumi API、国土地理院），不抓取商业巡礼站点，也不搬运截图与博客原文。

## 结构

```
sync/            数据同步与导出（Python）；places / bgm / geocheck / notes / translate 是整理与补全步骤
db/schema.ts     D1 表结构：bangumi、point
routes/v1/       读接口：/v1/search?q=、/v1/bangumi/:id（不放 /api 下，才能被边缘缓存）
pages/           页面（Void Pages 模式）；index 是地图 + 搜索 + 作品详情
src/             前端组件与工具；theme.css 是全站唯一的配色定义，map-style.ts 是地图皮肤
public/data/     地图点位 points.geojson（gzip 后约 0.7 MB）
```

- 地图上的 5 万多个点位是静态 GeoJSON，MapLibre 在 worker 里加载并聚合。
- 搜索是全语种、模糊的：名称都先「折叠」（简繁、平片假名、全半角、大小写、标点归一，日文另加罗马音），规则在 `sync/fold.py` 与 `src/fold.ts` 两处保持一致。作品在浏览器里用 `bangumi.json` 本地匹配；地标查 D1，折叠后的文本上建了 FTS5 trigram 索引，响应按查询词缓存在边缘，直到下次部署。
- 概览的封面墙跟随地图视口：浏览器用 `points.geojson` 统计视野内各作品的地标数。
- 数据更新的流程是 `pnpm data` → 导入远程 D1 → 部署；部署会清空边缘缓存。

## 数据来源与授权

- 同步用的是 Anitabi 主站前端自己加载的静态数据包 `/d/g.json`、`/d/g{n}.json`。**这不是公开接口**，格式可能随时变化；字段含义对照的是前端代码里的 `FD` / `DD` / `PD` 解析函数。
- 请求参数 `d` 默认按天取值，与主站一致，命中同一份 CDN 缓存，尽量不给源站添负担。
- 截图采用 CC BY-NC-SA 4.0：仅限非商业使用，展示时必须署名并链接来源，衍生作品需以相同协议发布。截图目前仍直接引用 `image.anitabi.cn` 的缩略图。
- 作品信息来自 [番组计划](https://bgm.tv)。底图来自 [OpenFreeMap](https://openfreemap.org)（OpenStreetMap 数据）。
