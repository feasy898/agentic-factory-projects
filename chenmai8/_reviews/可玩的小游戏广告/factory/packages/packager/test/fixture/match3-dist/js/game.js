/**
 * 占位工程游戏脚本：仅用于打包器自验收（不参与正式模板交付）。
 * 遵守运行时契约的形状：window.PF、pf:* 事件（真实实现见模板 + engine-bridge）。
 * landingUrl 出现在 JS 字符串中，用于验证"零外链扫描 + landingUrl 白名单"。
 */
(function () {
  "use strict";

  var LANDING_URL = "https://example.com/playable-lp";

  function dispatch(type, detail) {
    document.dispatchEvent(new CustomEvent(type, { detail: detail || null }));
  }

  window.PF = {
    locale: document.documentElement.getAttribute("lang") || "en",
    isMuted: function () {
      return true;
    },
    open: function (url) {
      dispatch("pf:cta", { url: url || LANDING_URL });
    },
  };

  function ready() {
    dispatch("pf:ready");
    var started = false;
    var moves = 0;
    document.getElementById("game").addEventListener("pointerdown", function () {
      if (!started) {
        started = true;
        dispatch("pf:first-interaction");
      }
      moves += 1;
      document.getElementById("score").textContent = "Score " + moves;
      if (moves >= 3) {
        dispatch("pf:end", { win: true });
        moves = 0;
      }
    });
    document.getElementById("cta").addEventListener("click", function () {
      window.PF.open(LANDING_URL);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
