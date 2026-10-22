import { bangumi, point } from "@schema";
import { defineHandler } from "void";
import { asc, db, eq } from "void/db";
import { z } from "zod";

export const GET = defineHandler.withValidator({
  params: z.object({ id: z.coerce.number().int().positive() }),
})(async (c, { params }) => {
  const [[info], points] = await Promise.all([
    db.select().from(bangumi).where(eq(bangumi.id, params.id)),
    db
      .select({
        id: point.id,
        name: point.name,
        cn: point.cn,
        lat: point.lat,
        lng: point.lng,
        ep: point.ep,
        s: point.s,
        image: point.image,
        origin: point.origin,
        originLink: point.originLink,
        mark: point.mark,
      })
      .from(point)
      .where(eq(point.bangumiId, params.id))
      .orderBy(asc(point.priority), asc(point.id)),
  ]);
  if (!info) return c.json({ error: "not found" }, 404);
  return { ...info, points };
});
