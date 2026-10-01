// pf/src/validate-cmd.ts — pf validate（oracle pfcore __main__.cmd_validate 语义移植）。
//
// 用法：node pf/pf.mjs validate <spec.json> [more.json / glob ...]
// glob 展开（Windows shell 不展开时由本命令自行展开）；任何 issue（含文件缺失/
// 解析失败）都计入失败；全部文件通过 exit 0，否则 exit 1。
// stdout 人读格式对齐 oracle（OK/INVALID/汇总行），门禁只断言 exit + {path, code}
//（spec-contract §2.5：消息人读不锁字节）。

import { readFileSync, statSync } from "node:fs";

import { validateSpec } from "../../packages/spec/src/validate.ts";
import type { SpecError } from "../../packages/spec/src/types.ts";
import { expandSpecPaths } from "./util.ts";

/** SpecError → oracle SpecIssue.render() 同形人读行。 */
function renderIssue(issue: SpecError): string {
  return `${issue.path}: ${issue.message} [${issue.code}]`;
}

/** 单文件校验（oracle validate_spec_file 同义：文件缺失/JSON 非法归一为带路径 issue）。 */
export function validateSpecFile(path: string): SpecError[] {
  let isFile = false;
  try {
    isFile = statSync(path).isFile();
  } catch { /* 不存在 */ }
  if (!isFile) {
    return [{ path: "$", message: `文件不存在：${path}`, code: "io-not-found" }];
  }
  let spec: unknown;
  try {
    spec = JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    return [{ path: "$", message: `读取/解析失败：${String(err)}`, code: "io-parse" }];
  }
  return validateSpec(spec).errors;
}

export interface ValidateArgs {
  spec: string[];
}

export function cmdValidate(args: ValidateArgs): number {
  const { files, unmatched } = expandSpecPaths(args.spec);
  let failures = 0;
  for (const pattern of unmatched) {
    console.log(`INVALID <pattern>: 模式无匹配文件：${pattern} [io-not-found]`);
    failures += 1;
  }
  if (files.length === 0 && unmatched.length === 0) {
    console.log("INVALID <args>: 未提供任何 spec 文件");
    return 1;
  }
  for (const file of files) {
    const issues = validateSpecFile(file);
    if (issues.length === 0) {
      console.log(`OK      ${file.replaceAll("\\", "/")}`);
      continue;
    }
    failures += 1;
    console.log(`INVALID ${file.replaceAll("\\", "/")}`);
    for (const issue of issues) console.log(`  ${renderIssue(issue)}`);
  }
  const total = files.length + unmatched.length;
  const passed = total - failures;
  console.log(`validate: ${passed}/${total} 通过`);
  return failures === 0 ? 0 : 1;
}
