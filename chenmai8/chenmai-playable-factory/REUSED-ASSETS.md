# REUSED-ASSETS.md — oracle 数据资产字节复用登记册

> 依据：`../plan/模式M-技术选型决策.md` §2「数据资产字节级复用」。
> 来源 oracle：`../repo/`（封存只读）。复制与逐项 sha256 比对执行日：2026-09-30（M1.1）。
> 本文件是复用资产的**唯一登记处**：下方 JSON 登记册由
> `node scripts/verify-reused-assets.mjs`（npm test 内含）逐项重算校验，漂移即失败。
> **改动下列任何文件 = 违约**（数据契约零变更，决策 §2.2）。

## A. 已复用（M1.1 起，累计 32 项，与 oracle 逐项 sha256 一致）

| # | factory 路径 | oracle 来源 | bytes | sha256 |
|---|---|---|---|---|
| 1 | `packages/spec/playable-spec.schema.json` | `repo/packages/spec/playable-spec.schema.json` | 13744 | `2d7e4248010b10a03ac46ad23a60fd1875d02af01eb59d100182902ee17ead5d` |
| 2 | `channel-rules/channel-rules.json` | `repo/channel-rules/channel-rules.json` | 8169 | `5ca74cf33d9f73415ad8813612fa05129e71e66ae621774d8ac9fffb6616228a` |
| 3 | `specs-eval/golden-match3.json` | `repo/specs-eval/golden-match3.json` | 3315 | `51d607aca7db1a967b73c7cc2d78fb03a73f37c8a5d5914df564fc9bfa32adda` |
| 4 | `specs-eval/golden-merge.json` | `repo/specs-eval/golden-merge.json` | 3340 | `17d21c5b5ac975eb7ade677c822a970fd365ae116eae35c5d5324f18ce0d7ab6` |
| 5 | `specs-eval/golden-pullpin.json` | `repo/specs-eval/golden-pullpin.json` | 3147 | `60dbe2f309d6d8340c0a9c065e2e1fd5f201b7f7ab8c0e4eda5c2b0c566455da` |
| 6 | `specs-eval/golden-sort.json` | `repo/specs-eval/golden-sort.json` | 3147 | `3675c130d70e41103715b42354ccdfb7c3a560c0dfe31003814473d29e3baad3` |
| 7 | `specs-eval/demo-zh.json` | `repo/specs-eval/demo-zh.json` | 1792 | `6b0ef8137c6fc2d3110a855386a8bd2be6a481f23777e75e3f897b1c73e57ef7` |
| 8 | `specs-eval/spike-manifest.json` | `repo/specs-eval/spike-manifest.json` | 3142 | `020f75f7c0a656c5ea09e6d889f040e06713fcbe9d3c1983b8ebbd5e246fb9f5` |
| 9 | `specs-eval/bad/01-missing-field.json` | `repo/specs-eval/bad/01-missing-field.json` | 905 | `7d3099664dd330eabeba8cfa9f2af5194719a2e652600e7e968d34920bd2cccf` |
| 10 | `specs-eval/bad/02-pullpin-unsolvable.json` | `repo/specs-eval/bad/02-pullpin-unsolvable.json` | 1218 | `7fb43e3537743a24dc33cfcaf9a8593ccd8e416df493de8ab40cfa8d4e51dab9` |
| 11 | `specs-eval/bad/03-duration-over-budget.json` | `repo/specs-eval/bad/03-duration-over-budget.json` | 1122 | `463e02a32ca0a35e284c381343ec0d77c1be8e2729a6d843acfd54f332a1b542` |
| 12 | `specs-eval/bad/04-missing-locale-strings.json` | `repo/specs-eval/bad/04-missing-locale-strings.json` | 1153 | `e4e7645de4605547915af863925d74361b89b5e32c2b66a43ca9f402c86d45c3` |
| 13 | `specs-eval/bad/05-bad-url.json` | `repo/specs-eval/bad/05-bad-url.json` | 1124 | `1bab9845cad3b8875ef8b2e610cbc27449fa4e055cf532ee9d3d7a12a007de26` |
| 14 | `specs-eval/bad/06-unknown-template.json` | `repo/specs-eval/bad/06-unknown-template.json` | 1008 | `5a4624b3b10a34aab21f8f5d412a023b0ab74a635447b3c5237bf1018d91447c` |
| 15 | `specs-eval/assets/demo-zh/piece-0.png` | `repo/specs-eval/assets/demo-zh/piece-0.png` | 893 | `5a84bdb464d1c94eba787a28d87e00a71d217de0d53a881cc14972eae66d69d4` |
| 16 | `packages/templates/vendor/engine.js` | `repo/packages/templates/tmpl-match3/src/vendor/engine.js` | 1207764 | `660aa854f150fdc8aac45f08114f644e1569e5ed9cfbfed09fc1b0f24de8a686` |
| 17 | `packages/packager/test/fixture/gen-pngs.mjs` | `repo/packages/packager/test/fixture/gen-pngs.mjs` | 1985 | `6fa1ce1d5b2584f020e23e61e6faf808443dbb6302146464811e599a5a77697a` |
| 18 | `packages/packager/test/fixture/match3-dist/index.html` | `repo/packages/packager/test/fixture/match3-dist/index.html` | 524 | `7ce9ff6447f94e0af04dd3edaccd8044eda9f387ebda40611eace5547b9360d1` |
| 19 | `packages/packager/test/fixture/match3-dist/css/style.css` | `repo/packages/packager/test/fixture/match3-dist/css/style.css` | 747 | `5b951e2bd40aa2c262fd002423cd114d0c31007fa34a024062ff3562d82b21d6` |
| 20 | `packages/packager/test/fixture/match3-dist/js/game.js` | `repo/packages/packager/test/fixture/match3-dist/js/game.js` | 1463 | `c47e8d5019e7927e76a86c8881bad776623e18a60ffadfb22a9e23cc92322d2d` |
| 21 | `packages/packager/test/fixture/match3-dist/img/bg.png` | `repo/packages/packager/test/fixture/match3-dist/img/bg.png` | 99 | `16da76528650bbae7e6323a7960abb6de2028ca3c4539d5153d91bf10e40c746` |
| 22 | `packages/packager/test/fixture/match3-dist/img/piece-0.png` | `repo/packages/packager/test/fixture/match3-dist/img/piece-0.png` | 79 | `e6e5c5c6c7d0a8e2fbea036018e256ebcd1cdb2276e8e7a71bae7f132e948a48` |
| 23 | `packages/packager/test/fixture/match3-dist/img/piece-1.png` | `repo/packages/packager/test/fixture/match3-dist/img/piece-1.png` | 79 | `9e6d1cbf859f76d4a5b4a72ad8a00265a8ccf23e996315e3f23670d3f0e29910` |
| 24 | `packages/packager/test/fixture/match3-dist/img/piece-2.png` | `repo/packages/packager/test/fixture/match3-dist/img/piece-2.png` | 79 | `b3a095bfc5b448fdb259ec4a46a7897d40008c4c688ba0de50caecde2deaa06a` |
| 25 | `docs/specs/packager.md` | `repo/docs/assets/specs/packager.md` | 17191 | `e40335f20c2189937c5c7d8873afd48c81ce1015dee8b8711f5c7b2bd8c2c1c7` |
| 26 | `packages/engine-bridge/test/channels.test.mjs` | `repo/packages/engine-bridge/test/channels.test.mjs` | 7415 | `77663c92f2b773bc32559779207d3ccd4a35b725ed686265540f6f2aebfa00fc` |
| 27 | `packages/engine-bridge/test/events.test.mjs` | `repo/packages/engine-bridge/test/events.test.mjs` | 3973 | `1039df677c367ee130a2fe52c3df95534e66021240b9dab6af2c604ddf927430` |
| 28 | `packages/engine-bridge/test/mute.test.mjs` | `repo/packages/engine-bridge/test/mute.test.mjs` | 4513 | `61208b106073d13d0b9ef3f932b3c4560041d4ffb9f88503a72605b322354f60` |
| 29 | `packages/engine-bridge/test/index.js` | `repo/packages/engine-bridge/test/index.js` | 707 | `736e32d985495e6f9f653a4edf5f15e45f9238816d8667752598d49360edab2b` |
| 30 | `packages/engine-bridge/test/run.mjs` | `repo/packages/engine-bridge/test/run.mjs` | 745 | `0b1de84412531b65f327941a24a8ecff99d31d9c5bef7ef85cc422c763195ce6` |
| 31 | `packages/engine-bridge/testsupport/fixture.mjs` | `repo/packages/engine-bridge/testsupport/fixture.mjs` | 4210 | `9726c3becca43f3cbfe48d21c20ca9971d1a5fdc1569e4668a6f311a34fd8963` |
| 32 | `docs/specs/engine-bridge.md` | `repo/docs/assets/specs/engine-bridge.md` | 11193 | `1b4866e8b63150549493f37f8cd451585925e3349af99b363318345fb4872a28` |

注（#16）：oracle 四个模板包（tmpl-match3/merge/pullpin/sort）内的 `src/vendor/engine.js`
互为同字节（sha256 全等 `660aa854…`），factory 以单一母本收存于
`packages/templates/vendor/`，M3 各模板包**字节复制**该母本。bundle 已中性化
（词表扫描 0 命中，本批复核），版本锚 3.88.2（REGENERATE 坑 2）。
注（#17–#24，M4 批次追加）：打包器冻结自验收夹具（spec packager.md §3.5/§6），整目录字节复制
（2026-09-30 实测 `diff -r` 与 oracle 全等）。
注（#26–#31，M1.2b 批次追加）：桥冻结测试整目录字节复制（26 用例 = channels/events/mute 三组；
`testsupport/fixture.mjs` 是夹具本体、与 test/ 同为冻结 eval 不可分割部分，一并登记）。
2026-09-30 实测 6 文件 sha256 与 oracle 逐项一致；本机直跑
`node packages/engine-bridge/test/run.mjs` → 26/26 pass exit 0。
注（#32，M1.2b 批次追加）：M2 资产 spec 文档字节复制（oracle docs/assets/ 是唯一规格源，决策 §0；
与 #25 同一处置方式）。
注（#25，M4 批次追加）：M4 资产 spec 文档字节复制（oracle docs/assets/ 是唯一规格源，决策 §0）。
注：冻结自验收 `packages/packager/test/run.mjs` **不在**字节登记册——按决策 §2.1 M4 行 +
P5 预declare 做**且仅做**一处移植：python zipfile 交叉验证断言 → 系统 bsdtar
（Windows 自带 `C:\Windows\System32\tar.exe`，libarchive 3.8.4；本机 `where tar` 首位是
Git 的 GNU tar 1.35，**不能读 zip**，故按绝对路径定位 bsdtar——此定位细节属移植脚本 glue，
语义保持：条目名 / 入口引用 / CRC）。SKIP 分支删除，断言总数恒定 46；
其余 45 条断言与 oracle `run.mjs` 逐字节一致。

### 机器可读登记册（verify-reused-assets.mjs 与 npm test 消费；勿手改数字）

```json
{
  "registryVersion": 1,
  "copiedAt": "2026-09-30",
  "assets": [
    { "path": "packages/spec/playable-spec.schema.json", "source": "repo/packages/spec/playable-spec.schema.json", "bytes": 13744, "sha256": "2d7e4248010b10a03ac46ad23a60fd1875d02af01eb59d100182902ee17ead5d" },
    { "path": "channel-rules/channel-rules.json", "source": "repo/channel-rules/channel-rules.json", "bytes": 8169, "sha256": "5ca74cf33d9f73415ad8813612fa05129e71e66ae621774d8ac9fffb6616228a" },
    { "path": "specs-eval/golden-match3.json", "source": "repo/specs-eval/golden-match3.json", "bytes": 3315, "sha256": "51d607aca7db1a967b73c7cc2d78fb03a73f37c8a5d5914df564fc9bfa32adda" },
    { "path": "specs-eval/golden-merge.json", "source": "repo/specs-eval/golden-merge.json", "bytes": 3340, "sha256": "17d21c5b5ac975eb7ade677c822a970fd365ae116eae35c5d5324f18ce0d7ab6" },
    { "path": "specs-eval/golden-pullpin.json", "source": "repo/specs-eval/golden-pullpin.json", "bytes": 3147, "sha256": "60dbe2f309d6d8340c0a9c065e2e1fd5f201b7f7ab8c0e4eda5c2b0c566455da" },
    { "path": "specs-eval/golden-sort.json", "source": "repo/specs-eval/golden-sort.json", "bytes": 3147, "sha256": "3675c130d70e41103715b42354ccdfb7c3a560c0dfe31003814473d29e3baad3" },
    { "path": "specs-eval/demo-zh.json", "source": "repo/specs-eval/demo-zh.json", "bytes": 1792, "sha256": "6b0ef8137c6fc2d3110a855386a8bd2be6a481f23777e75e3f897b1c73e57ef7" },
    { "path": "specs-eval/spike-manifest.json", "source": "repo/specs-eval/spike-manifest.json", "bytes": 3142, "sha256": "020f75f7c0a656c5ea09e6d889f040e06713fcbe9d3c1983b8ebbd5e246fb9f5" },
    { "path": "specs-eval/bad/01-missing-field.json", "source": "repo/specs-eval/bad/01-missing-field.json", "bytes": 905, "sha256": "7d3099664dd330eabeba8cfa9f2af5194719a2e652600e7e968d34920bd2cccf" },
    { "path": "specs-eval/bad/02-pullpin-unsolvable.json", "source": "repo/specs-eval/bad/02-pullpin-unsolvable.json", "bytes": 1218, "sha256": "7fb43e3537743a24dc33cfcaf9a8593ccd8e416df493de8ab40cfa8d4e51dab9" },
    { "path": "specs-eval/bad/03-duration-over-budget.json", "source": "repo/specs-eval/bad/03-duration-over-budget.json", "bytes": 1122, "sha256": "463e02a32ca0a35e284c381343ec0d77c1be8e2729a6d843acfd54f332a1b542" },
    { "path": "specs-eval/bad/04-missing-locale-strings.json", "source": "repo/specs-eval/bad/04-missing-locale-strings.json", "bytes": 1153, "sha256": "e4e7645de4605547915af863925d74361b89b5e32c2b66a43ca9f402c86d45c3" },
    { "path": "specs-eval/bad/05-bad-url.json", "source": "repo/specs-eval/bad/05-bad-url.json", "bytes": 1124, "sha256": "1bab9845cad3b8875ef8b2e610cbc27449fa4e055cf532ee9d3d7a12a007de26" },
    { "path": "specs-eval/bad/06-unknown-template.json", "source": "repo/specs-eval/bad/06-unknown-template.json", "bytes": 1008, "sha256": "5a4624b3b10a34aab21f8f5d412a023b0ab74a635447b3c5237bf1018d91447c" },
    { "path": "specs-eval/assets/demo-zh/piece-0.png", "source": "repo/specs-eval/assets/demo-zh/piece-0.png", "bytes": 893, "sha256": "5a84bdb464d1c94eba787a28d87e00a71d217de0d53a881cc14972eae66d69d4" },
    { "path": "packages/templates/vendor/engine.js", "source": "repo/packages/templates/tmpl-match3/src/vendor/engine.js", "bytes": 1207764, "sha256": "660aa854f150fdc8aac45f08114f644e1569e5ed9cfbfed09fc1b0f24de8a686" },
    { "path": "packages/packager/test/fixture/gen-pngs.mjs", "source": "repo/packages/packager/test/fixture/gen-pngs.mjs", "bytes": 1985, "sha256": "6fa1ce1d5b2584f020e23e61e6faf808443dbb6302146464811e599a5a77697a" },
    { "path": "packages/packager/test/fixture/match3-dist/index.html", "source": "repo/packages/packager/test/fixture/match3-dist/index.html", "bytes": 524, "sha256": "7ce9ff6447f94e0af04dd3edaccd8044eda9f387ebda40611eace5547b9360d1" },
    { "path": "packages/packager/test/fixture/match3-dist/css/style.css", "source": "repo/packages/packager/test/fixture/match3-dist/css/style.css", "bytes": 747, "sha256": "5b951e2bd40aa2c262fd002423cd114d0c31007fa34a024062ff3562d82b21d6" },
    { "path": "packages/packager/test/fixture/match3-dist/js/game.js", "source": "repo/packages/packager/test/fixture/match3-dist/js/game.js", "bytes": 1463, "sha256": "c47e8d5019e7927e76a86c8881bad776623e18a60ffadfb22a9e23cc92322d2d" },
    { "path": "packages/packager/test/fixture/match3-dist/img/bg.png", "source": "repo/packages/packager/test/fixture/match3-dist/img/bg.png", "bytes": 99, "sha256": "16da76528650bbae7e6323a7960abb6de2028ca3c4539d5153d91bf10e40c746" },
    { "path": "packages/packager/test/fixture/match3-dist/img/piece-0.png", "source": "repo/packages/packager/test/fixture/match3-dist/img/piece-0.png", "bytes": 79, "sha256": "e6e5c5c6c7d0a8e2fbea036018e256ebcd1cdb2276e8e7a71bae7f132e948a48" },
    { "path": "packages/packager/test/fixture/match3-dist/img/piece-1.png", "source": "repo/packages/packager/test/fixture/match3-dist/img/piece-1.png", "bytes": 79, "sha256": "9e6d1cbf859f76d4a5b4a72ad8a00265a8ccf23e996315e3f23670d3f0e29910" },
    { "path": "packages/packager/test/fixture/match3-dist/img/piece-2.png", "source": "repo/packages/packager/test/fixture/match3-dist/img/piece-2.png", "bytes": 79, "sha256": "b3a095bfc5b448fdb259ec4a46a7897d40008c4c688ba0de50caecde2deaa06a" },
    { "path": "docs/specs/packager.md", "source": "repo/docs/assets/specs/packager.md", "bytes": 17191, "sha256": "e40335f20c2189937c5c7d8873afd48c81ce1015dee8b8711f5c7b2bd8c2c1c7" },
    { "path": "packages/engine-bridge/test/channels.test.mjs", "source": "repo/packages/engine-bridge/test/channels.test.mjs", "bytes": 7415, "sha256": "77663c92f2b773bc32559779207d3ccd4a35b725ed686265540f6f2aebfa00fc" },
    { "path": "packages/engine-bridge/test/events.test.mjs", "source": "repo/packages/engine-bridge/test/events.test.mjs", "bytes": 3973, "sha256": "1039df677c367ee130a2fe52c3df95534e66021240b9dab6af2c604ddf927430" },
    { "path": "packages/engine-bridge/test/mute.test.mjs", "source": "repo/packages/engine-bridge/test/mute.test.mjs", "bytes": 4513, "sha256": "61208b106073d13d0b9ef3f932b3c4560041d4ffb9f88503a72605b322354f60" },
    { "path": "packages/engine-bridge/test/index.js", "source": "repo/packages/engine-bridge/test/index.js", "bytes": 707, "sha256": "736e32d985495e6f9f653a4edf5f15e45f9238816d8667752598d49360edab2b" },
    { "path": "packages/engine-bridge/test/run.mjs", "source": "repo/packages/engine-bridge/test/run.mjs", "bytes": 745, "sha256": "0b1de84412531b65f327941a24a8ecff99d31d9c5bef7ef85cc422c763195ce6" },
    { "path": "packages/engine-bridge/testsupport/fixture.mjs", "source": "repo/packages/engine-bridge/testsupport/fixture.mjs", "bytes": 4210, "sha256": "9726c3becca43f3cbfe48d21c20ca9971d1a5fdc1569e4668a6f311a34fd8963" },
    { "path": "docs/specs/engine-bridge.md", "source": "repo/docs/assets/specs/engine-bridge.md", "bytes": 11193, "sha256": "1b4866e8b63150549493f37f8cd451585925e3349af99b363318345fb4872a28" },
    { "path": "packages/spec/test/ajv-check.mjs", "source": "repo/packages/spec/test/ajv-check.mjs", "bytes": 2724, "sha256": "18b98572e7ff342e6258da3cb79b47f2488e5d7f168f5b6307e79cf908114b8c" }
  ]
}
```

## B. 决策 §2 复用清单其余项（后续模块批次拷贝，拷贝时逐项 sha 校验并回填本表）

| 资产 | oracle 来源 | 落位 | 批次 |
|---|---|---|---|
| 桥冻结测试（26 用例：events/channels/mute + index.js + run.mjs + testsupport/fixture.mjs） | `repo/packages/engine-bridge/test/`、`testsupport/` | `packages/engine-bridge/test/` | **M2 已落**（A 节 #26–#31 字节登记；26/26 exit 0 + coverage 97.6% + tsc strict 实测过） |
| packager 冻结自验收（46 断言：run.mjs + fixture/gen-pngs.mjs + fixture/match3-dist/） | `repo/packages/packager/test/` | `packages/packager/test/` | **M4 已落**（run.mjs 含 P5 单点移植，见 A 节注；fixture/gen-pngs 已字节登记） |
| spec 冻结 ajv-check | `repo/packages/spec/test/ajv-check.mjs` | `packages/spec/test/` | **M1 已落**（A 节末条 #33 字节登记，cmp 与 oracle 字节全等；经 `src/validate.mjs` 壳原样跑通 AJV-CHECK: PASS exit 0，2026-09-30） |
| qacore mini.html 夹具 | `repo/python/qacore/tests/fixtures/mini.html` | `qacore/tests/fixtures/` | M8 |

（M1.1 验收口径：A 节 16 项与 oracle 逐项 sha256 一致——已实测全 MATCH；B 节按所属模块批次拷贝并登记。）
