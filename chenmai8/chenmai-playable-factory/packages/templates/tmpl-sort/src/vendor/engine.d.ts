// 渲染引擎的类型垫片（中性名）。
// src/vendor/engine.js 是离线 vendor 流程生成的引擎单文件构建产物（已压缩、
// 已做内部标识与字符串中性化），构建脚本从 packages/templates/vendor/engine.js
// 母本字节复制（sha256 锚定见 REUSED-ASSETS.md #16）；本文件仅为类型检查
// 声明模板实际用到的导出面，全部按 any 处理。
export declare const Game: any;
export declare const Scene: any;
export declare const AUTO: number;
export declare const CANVAS: number;
export declare const WEBGL: number;
export declare const Scale: any;
export declare const GameObjects: any;
export declare const Geom: any;
export declare const Input: any;
export declare const Math: any;
export declare const Display: any;
export declare const Actions: any;
export declare const Tweens: any;
export declare const Sound: any;
export declare const Cameras: any;
export declare const Loader: any;
export declare const Textures: any;
export declare const VERSION: string;
