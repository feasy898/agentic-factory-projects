// test/ 目录入口：`node --test packages/engine-bridge/test/` 在本机 Node 22
// (Windows) 下不展开目录参数，而是把目录作为单一入口执行；本文件即该入口，
// 负责在进程内装载全部用例（import 即向 node:test 注册，进程退出前自动执行）。
//
// 在会展开目录参数的 Node 版本上，本文件会额外被当作"用例文件"收集一次，
// 此时全部用例会在本子进程内再跑一遍——结果仍全绿、exit code 语义不变，
// 用例本身幂等（每例独立 jsdom），故不做环境判断、始终装载。

await import("./channels.test.mjs");
await import("./events.test.mjs");
await import("./mute.test.mjs");
