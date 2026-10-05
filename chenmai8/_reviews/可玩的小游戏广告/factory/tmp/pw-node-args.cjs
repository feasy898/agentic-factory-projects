
const { chromium } = require("playwright");
(async () => {
  const b = await chromium.launch({ headless: true });
  console.log("NODE_VERSION:", b.version());
  const p = b.browserType()._channel || {};
  console.log("ARGS:", JSON.stringify((b.options && b.options.args) || [], null, 0));
  // read chrome process cmdline via process property (internal)
  await b.close();
})();
