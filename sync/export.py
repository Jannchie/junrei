"""把 sync.sync 同步下来的 data/anitabi.sqlite 转成应用使用的数据（只做格式转换，规范化在 sync.sync 里）：

  data/d1-import.sql          全量覆盖 D1 的 bangumi / point 表并重建全文索引（pnpm data:import）
  data/stats.json             首页统计，构建时打进前端，不必每次访问都查 D1
  public/data/points.geojson  地图点位，maplibre 在 worker 里直接加载并聚合

  python -m sync.export
"""

from __future__ import annotations

import sqlite3
import sys

from sync.sync import DEFAULT_OUT, attribution, valid_geo, write_json

PUBLIC_DATA = DEFAULT_OUT.parent / "public" / "data"
ROWS_PER_INSERT = 200  # D1 单条语句有长度上限，分批插入


def sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert_statements(table: str, cols: list[str], rows: list[tuple]):
    head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n"
    for i in range(0, len(rows), ROWS_PER_INSERT):
        chunk = rows[i : i + ROWS_PER_INSERT]
        yield head + ",\n".join("(" + ", ".join(sql_value(v) for v in r) + ")" for r in chunk) + ";\n"


def main():
    src = sqlite3.connect(DEFAULT_OUT / "anitabi.sqlite")

    points = []
    for (bid, pid, name, cn, lat, lng, prio, ep, s, image, origin, link, mark) in src.execute(
        """SELECT p.bangumi_id, p.id, p.name, p.cn, p.lat, p.lng, p.priority, p.ep, p.s, p.image,
                  p.origin, p.origin_link, p.mark
           FROM point p JOIN bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0 ORDER BY p.bangumi_id, p.priority, p.id"""):
        if not valid_geo(lat, lng):
            continue
        if image:
            origin, link = attribution(bid, pid, origin, link)
        points.append((bid, pid, name, cn, lat, lng, prio, ep, s, image, origin, link, mark))

    counts: dict[int, int] = {}
    for p in points:
        counts[p[0]] = counts.get(p[0], 0) + 1
    bangumi = [
        (*row, counts.get(row[0], 0))
        for row in src.execute(
            "SELECT id, cn, title, en, city, cat, color, cover FROM bangumi WHERE deleted = 0 ORDER BY id")
    ]

    out_sql = DEFAULT_OUT / "d1-import.sql"
    with out_sql.open("w", encoding="utf-8") as f:
        f.write("DELETE FROM point;\nDELETE FROM bangumi;\n")
        cols = ["id", "cn", "title", "en", "city", "cat", "color", "cover", "point_count"]
        f.writelines(insert_statements("bangumi", cols, bangumi))
        cols = ["bangumi_id", "id", "name", "cn", "lat", "lng", "priority", "ep", "s", "image", "origin",
                "origin_link", "mark"]
        f.writelines(insert_statements("point", cols, points))
        f.write("INSERT INTO point_fts(point_fts) VALUES('rebuild');\n")

    # 坐标保留 5 位小数（约 1 m）；属性只留点击时需要的作品 id 和地标 id
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    out_geo = PUBLIC_DATA / "points.geojson"
    write_json(out_geo, {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(p[5], 5), round(p[4], 5)]},
             "properties": {"b": p[0], "p": p[1]}}
            for p in points
        ],
    })

    modified = src.execute("SELECT max(modified) FROM bangumi WHERE deleted = 0").fetchone()[0]
    write_json(DEFAULT_OUT / "stats.json", {"bangumi": len(bangumi), "points": len(points), "modified": modified})

    print(f"{out_sql}：{len(bangumi)} 部作品，{len(points)} 个地标，{out_sql.stat().st_size / 1e6:.1f} MB")
    print(f"{out_geo}：{out_geo.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]  # Windows 控制台默认不是 UTF-8
    main()
