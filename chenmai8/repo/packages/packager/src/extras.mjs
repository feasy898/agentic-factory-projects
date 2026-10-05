/**
 * 渠道声明生成文件（channel-rules package.generated）的构建器。
 *
 * zip 渠道包内、非模板 dist 产物的附加工件由此按 spec 现生成：
 *   - "tiktok-config"：TikTok/Pangle 渠道 config.json（version/orientation/gameName，
 *     字段为内部草拟，官方规范 D9 实测回填——见规则库该渠道 source）。
 *   - "js-sdk-stub"：渠道 js-sdk 运行时桩（js-sdk.js）：容器已注入真实实现时让位，
 *     仅在缺失时兜底定义退出全局，保证试玩内退出调用可观察、不抛错。
 *
 * 生成器名是规则库的稳定契约：package.generated 的值即此处支持的 kind；
 * 未知名直接抛错（配置拼错不应静默产出缺件包）。引擎中性、零上游依赖。
 */

/** spec.channels.orientation（portrait|landscape|both）原样透传；缺省 portrait。 */
function configOrientation(spec) {
  const v = spec?.channels?.orientation;
  return typeof v === "string" && v ? v : "portrait";
}

/**
 * @param {string} kind 生成器名（规则库 package.generated 的值）
 * @param {object} ctx { spec }（spec 为解析后的 PlayableSpec 对象）
 * @returns {string} 文件文本内容（UTF-8）
 */
export function generateExtra(kind, ctx) {
  const spec = ctx?.spec ?? {};
  switch (kind) {
    case "tiktok-config": {
      const config = {
        version: "1.0.0",
        orientation: configOrientation(spec),
        gameName: String(spec?.meta?.title ?? "").slice(0, 60),
      };
      return `${JSON.stringify(config, null, 2)}\n`;
    }
    case "js-sdk-stub":
      return [
        "/* pf-packager: 渠道 js-sdk 运行时桩。",
        " * 投放环境中由渠道容器提供真实实现；本桩仅在容器未注入同名全局时兜底定义，",
        " * 保证试玩内退出调用可观察、不抛错（引擎中性，无任何网络行为）。 */",
        "(function () {",
        '  "use strict";',
        '  if (typeof window === "undefined") return;',
        '  if (typeof window.openAppStore === "function") return;',
        "  window.openAppStore = function () { /* 桩：容器实现缺失时的兜底，无操作 */ };",
        "})();",
        "",
      ].join("\n");
    default:
      throw new Error(
        `未知的生成文件类型: "${kind}"（规则库 package.generated 的值须为打包器已实现的生成器）`);
  }
}
