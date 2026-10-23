import type { InferProps } from "void";
import { homeLoader, homePageHead } from "../src/server/pages";

export const loader = homeLoader;
export type Props = InferProps<typeof loader>;
export const head = homePageHead;
