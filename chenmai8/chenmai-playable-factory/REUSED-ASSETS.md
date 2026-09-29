# REUSED-ASSETS.md — oracle 数据资产字节复用登记册

> 依据：`../plan/模式M-技术选型决策.md` §2「数据资产字节级复用」。
> 来源 oracle：`../repo/`（封存只读）。复制与逐项 sha256 比对执行日：2026-09-30（M1.1）。
> 本文件是复用资产的**唯一登记处**：下方 JSON 登记册由
> `node scripts/verify-reused-assets.mjs`（npm test 内含）逐项重算校验，漂移即失败。
> **改动下列任何文件 = 违约**（数据契约零变更，决策 §2.2）。

## A. 已复用（本批 M1.1，16 项，与 oracle 逐项 sha256 一致）

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

注（#16）：oracle 四个模板包（tmpl-match3/merge/pullpin/sort）内的 `src/vendor/engine.js`
互为同字节（sha256 全等 `660aa854…`），factory 以单一母本收存于
`packages/templates/vendor/`，M3 各模板包**字节复制**该母本。bundle 已中性化
（词表扫描 0 命中，本批复核），版本锚 3.88.2（REGENERATE 坑 2）。

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
    { "path": "packages/templates/vendor/engine.js", "source": "repo/packages/templates/tmpl-match3/src/vendor/engine.js", "bytes": 1207764, "sha256": "660aa854f150fdc8aac45f08114f644e1569e5ed9cfbfed09fc1b0f24de8a686" }
  ]
}
```

## B. 决策 §2 复用清单其余项（后续模块批次拷贝，拷贝时逐项 sha 校验并回填本表）

| 资产 | oracle 来源 | 落位 | 批次 |
|---|---|---|---|
| 桥冻结测试（26 用例：events/channels/mute + index.js + run.mjs + testsupport/fixture.mjs） | `repo/packages/engine-bridge/test/`、`testsupport/` | `packages/engine-bridge/test/` | M2 |
| packager 冻结自验收（46 断言：run.mjs + fixture/gen-pngs.mjs + fixture/match3-dist/） | `repo/packages/packager/test/` | `packages/packager/test/` | M4 |
| spec 冻结 ajv-check | `repo/packages/spec/test/ajv-check.mjs` | `packages/spec/test/` | M1（模块任务） |
| qacore mini.html 夹具 | `repo/python/qacore/tests/fixtures/mini.html` | `qacore/tests/fixtures/` | M8 |

（M1.1 验收口径：A 节 16 项与 oracle 逐项 sha256 一致——已实测全 MATCH；B 节按所属模块批次拷贝并登记。）
