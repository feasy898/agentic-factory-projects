// packages/assetkit/src/types.ts — 素材清单与结果条目类型（oracle dataclass 同形）。

/** 一个待处理素材：绝对路径 + optmap 键 + 类别。 */
export interface Material {
  src: string;
  /** optmap 键：spec 声明的相对路径串（spec 来源）或规范化绝对路径。 */
  key: string;
  kind: "image" | "audio" | "font";
}

/** 逐素材结果条目（report.json materials[*] 与 optmap entries 的行）。 */
export interface AssetEntry {
  key: string;
  src: string;
  kind: Material["kind"];
  status: "optimized" | "kept-original" | "failed";
  out?: string | null;
  encoding?: string;
  originalBytes?: number;
  optimizedBytes?: number;
  reductionPct?: number;
  width?: number | null;
  height?: number | null;
  alpha?: boolean;
  candidates?: Array<{ encoding: string; bytes?: number; error?: string }>;
  charsRequested?: number;
  charsCovered?: number;
  note: string;
}
