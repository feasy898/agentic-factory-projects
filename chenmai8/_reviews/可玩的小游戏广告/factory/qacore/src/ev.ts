/**
 * evaluate 适配：oracle（playwright-python）的 page.evaluate 接受 "函数源码字符串"
 * 并自动识别调用；playwright-node 对字符串一律按**表达式**求值—— "() => …" 会
 * 求值出一个函数对象（序列化为 undefined）。本辅助把移植过来的函数源码字符串
 * 包成真函数（IIFE 表达式体），保持逐字照抄的探测/驱动表达式不变。
 */
import type { Page } from "playwright";

export function ev<T = unknown>(page: Page, functionSource: string): Promise<T> {
  const fn = new Function(`return (${functionSource})();`) as () => T;
  return page.evaluate(fn);
}
