/**
 * 规则库消费（CHK01/CHK04 输入，qacore spec §6.1）：
 * 真源 = channel-rules/channel-rules.json（数据资产，字节复用）。
 * - maxBytes：规则库无该渠道 → null → CHK01 skip（不假定）；
 * - muteBeforeFirstInteraction 取值次序：渠道 runtime > defaults > true
 *   （规则库不可读时也从严取 true）；
 * - runtime.injectRelativeScripts：容器运行时相对脚本（如 mraid.js），
 *   本地缺失时由伺服路由以桩应答；规则库不可读时返回空表（退回真实 404）。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { repoRoot } from "./server.ts";

const RULES_PATH = join(repoRoot(), "channel-rules", "channel-rules.json");

interface RulesDoc {
  defaults?: { muteBeforeFirstInteraction?: boolean };
  channels?: Record<string, {
    maxBytes?: unknown;
    runtime?: { muteBeforeFirstInteraction?: unknown; injectRelativeScripts?: unknown };
  }>;
}

function readRules(): RulesDoc | null {
  try {
    return JSON.parse(readFileSync(RULES_PATH, "utf8")) as RulesDoc;
  } catch {
    return null;
  }
}

export function loadChannelLimit(channel: string): number | null {
  const rules = readRules();
  const entry = rules?.channels?.[channel];
  if (rules && entry && typeof entry === "object" && Number.isInteger(entry.maxBytes)) {
    return entry.maxBytes as number;
  }
  return null;
}

export function loadChannelRuntimeScripts(channel: string): string[] {
  const rules = readRules();
  const scripts = rules?.channels?.[channel]?.runtime?.injectRelativeScripts;
  if (Array.isArray(scripts)) {
    return scripts.filter((s): s is string => typeof s === "string");
  }
  return [];
}

export function loadChannelMuteRequired(channel: string): boolean {
  const rules = readRules();
  if (!rules) return true;
  const entry = rules.channels?.[channel];
  if (entry && typeof entry === "object") {
    const runtime = entry.runtime;
    if (runtime && typeof runtime === "object" && "muteBeforeFirstInteraction" in runtime) {
      return Boolean(runtime.muteBeforeFirstInteraction);
    }
  }
  const defaults = rules.defaults;
  if (defaults && typeof defaults === "object" && "muteBeforeFirstInteraction" in defaults) {
    return Boolean(defaults.muteBeforeFirstInteraction);
  }
  return true;
}
