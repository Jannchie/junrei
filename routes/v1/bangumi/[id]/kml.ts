import { defineHandler } from "void";
import { z } from "zod";
import { LOCALES } from "../../../../src/i18n";
import { getBangumi } from "../../../../src/server/bangumi";
import { bangumiKml } from "../../../../src/server/kml";

// /v1/bangumi/:id/kml?lang=ja：下载作品的全部地标，地名按 lang 选语言
export const GET = defineHandler.withValidator({
  params: z.object({ id: z.coerce.number().int().positive() }),
  query: z.object({ lang: z.enum(LOCALES).default("zh-Hans") }),
})(async (c, { params, query }) => {
  const detail = await getBangumi(params.id);
  if (!detail) return c.json({ error: "not found" }, 404);
  const { name, kml } = bangumiKml(query.lang, detail);
  return new Response(kml, {
    headers: {
      "Content-Type": "application/vnd.google-earth.kml+xml; charset=utf-8",
      "Content-Disposition": `attachment; filename="junrei-${detail.id}.kml"; filename*=UTF-8''${encodeURIComponent(name.replace(/[\/:*?"<>|]/g, "_"))}.kml`,
    },
  });
});
