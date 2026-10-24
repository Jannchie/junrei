import type { InferProps } from "void";
import { recentLoader, recentPageHead } from "../src/server/pages";

export const loader = recentLoader;
export type Props = InferProps<typeof loader>;
export const head = recentPageHead;
