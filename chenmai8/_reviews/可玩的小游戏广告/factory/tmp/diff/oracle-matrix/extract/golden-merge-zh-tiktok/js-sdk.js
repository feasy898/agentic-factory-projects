/* pf-packager: 渠道 js-sdk 运行时桩。
 * 投放环境中由渠道容器提供真实实现；本桩仅在容器未注入同名全局时兜底定义，
 * 保证试玩内退出调用可观察、不抛错（引擎中性，无任何网络行为）。 */
(function () {
  "use strict";
  if (typeof window === "undefined") return;
  if (typeof window.openAppStore === "function") return;
  window.openAppStore = function () { /* 桩：容器实现缺失时的兜底，无操作 */ };
})();
