import type { InferProps } from "void";
import { privacyLoader, privacyPageHead } from "../src/server/pages";

export const loader = privacyLoader;
export type Props = InferProps<typeof loader>;
export const head = privacyPageHead;
