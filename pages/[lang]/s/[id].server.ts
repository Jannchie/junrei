import type { InferProps } from "void";
import { groupLoader, groupPageHead } from "../../../src/server/pages";

export const loader = groupLoader(true);
export type Props = InferProps<typeof loader>;
export const head = groupPageHead;
