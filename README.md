# junrei

更好用的动画圣地巡礼地图，计划部署在 <https://junrei.jannchie.com>。

数据来自 [Anitabi](https://www.anitabi.cn/map)：定时全量同步到自己的数据库，线上查询全部走自己的 D1 和静态文件，运行时不请求 Anitabi 的 API。

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

`data/` 和 `public/data/` 都是生成物，不进 git；构建前需要先跑过 `pnpm data`。

## 结构

```
sync/            数据同步与导出（Python）
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
