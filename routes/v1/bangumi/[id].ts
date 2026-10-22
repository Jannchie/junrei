import { defineHandler } from "void";
import { z } from "zod";
import { getBangumi } from "../../../src/server/bangumi";

export const GET = defineHandler.withValidator({
  params: z.object({ id: z.coerce.number().int().positive() }),
})(async (c, { params }) => {
  const detail = await getBangumi(params.id);
  if (!detail) return c.json({ error: "not found" }, 404);
  return detail;
});
