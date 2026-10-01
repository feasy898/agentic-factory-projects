# ohos-tailscale 核心库 TypeScript/ArkTS 工程约束

- 生成日期：2026-09-28
- 适用范围：`packages/` 下全部 TypeScript 源码（核心库 + 测试）；`app/`（HarmonyOS 工程壳）另行约束
- 双目标：
  1. **Node 22 直接运行测试**（type stripping，不加转译器）；
  2. **最大程度兼容 ArkTS 语法约束**，日后低成本搬进 HarmonyOS 工程。
- 验证环境（本机实测，见附录 A）：Node v22.23.2（win32，type stripping 未加 flag 直接可用）、TypeScript tsgo 7.0.2、@types/node 22.x。
- 规则依据：OpenHarmony 官方《从 TypeScript 到 ArkTS 的适配规则》（`openharmony/docs` GitHub 镜像 `master` 分支 `zh-cn/application-dev/quick-start/typescript-to-arkts-migration-guide.md`，2026-09-28 抓取 99,951 字节；developer.huawei.com 在线页为 SPA，curl 只能取到外壳，见 §6-U1）。
- 编号约定：`A*` = ArkTS 禁则（§1）；`P*` = 本项目工程约束（§2）；`T*` = 工具链/tsconfig 约束（§3）。

---

## 0. 迁移方向性结论（为什么核心库保持 .ts）

官方规则 `arkts-no-ts-deps`：**允许 `.ets` 文件 import `.ets/.ts/.js` 源码；不允许 `.ts/.js` 文件 import `.ets` 源码**。依赖方向是单向的：

```
.ets（UI/Ability 层）──► .ts（核心库）   ✔ 允许
.ts（核心库）       ──► .ets           ✘ 编译错误
```

因此核心库保持纯 `.ts`、不依赖任何 ArkTS/UI 专有代码，正是低成本迁移的正确形态；迁移时只需在 `app/` 的 `.ets` 侧 import 本库。

---

## 1. ArkTS 相对 TypeScript 的主要禁则

> 每条给出官方规则名（`arkts-*`，部分附错误码）与正反例。反例在 TS（本项目当前）能编译/运行，但搬入 ArkTS 会编译失败；**写代码时按正例写**。

### A1 禁 `any` / `unknown`，必须显式静态类型

官方规则 `arkts-no-any-unknown`。ArkTS 强制静态类型，任何位置（变量、参数、返回值、泛型实参、数组元素）都不得出现 `any`/`unknown`，也没有隐式 `any`。

```typescript
// ✗ 反例（ArkTS 禁止）
let res: any = call('hello');
function parse(raw: unknown) { return raw as Config; }
let cache = [];            // TS 推断 any[]，ArkTS 报错

// ✓ 正例
class CallResult { public succeeded(): boolean { return false; } }
let res: CallResult = call('hello');
function parse(raw: Uint8Array): Config { return decode(raw); }
let cache: Map<string, Config> = new Map();
```

### A2 对象字面量必须显式标注类型，且不能直接初始化某些类

官方规则 `arkts-no-untyped-obj-literals`（错误码 10605038）。本条即"无类型对象字面量不能直接当 class 实例用"：

- 字面量只能赋给**显式标注**的 class/interface 类型（上下文可推断时可省略标注）；
- **不能**赋给 `any`、`Object`、`object` 类型；
- **不能**初始化带方法的类/接口；
- **不能**初始化含自定义含参构造函数的类；
- **不能**初始化带 `readonly` 字段的类。

```typescript
// ✗ 反例（ArkTS 禁止）
let o1 = { n: 42, s: 'foo' };              // 无类型标注
let o2: Object = { n: 42, s: 'foo' };      // 目标是 Object
class C2 { public s: string = ''; constructor(s: string) { this.s = s; } }
let o4: C2 = { s: 'foo' };                 // C2 有含参构造函数
class Svc { start(): void {} }             // 带方法的类
let o5: Svc = {} as Svc;                   // 绕不过

// ✓ 正例：字段全部显式声明、无方法/无含参构造/无 readonly 字段时可用字面量
interface PeerInfo { id: string; port: number }
let p: PeerInfo = { id: 'abc', port: 41641 };
class C1 { public n: number = 0; public s: string = ''; }
let o: C1 = { n: 42, s: 'foo' };
```

工程含义：数据载体（消息、配置、握手参数）定义为**纯字段 interface**，放在 `packages/common`；含行为的类型用 class 并 `new`。

### A3 不支持结构化类型（structural typing）

官方规则 `arkts-no-structural-typing`（错误码 10605030）。TS 按"形状"兼容类型；ArkTS 只认**名义关系**（继承 / implements 同一接口 / 类型别名）。两个 shape 相同但无名义关系的类互相赋值、互相传参都是编译错误。

```typescript
// ✗ 反例（TS 允许、ArkTS 禁止）
class T { public name: string = ''; }
class U { public name: string = ''; }      // shape 与 T 相同
let u: U = new T();                        // ArkTS 编译错误
function greeter(x: U): void {}
greeter(new T());                          // ArkTS 编译错误

// ✓ 正例：建立名义关系
interface Greeter { name: string }
class T implements Greeter { public name: string = ''; }
class U implements Greeter { public name: string = ''; }
let g: Greeter = new T();                  // ✔ 经共同接口
class D extends U { public extra: number = 0; }
let u2: U = new D();                       // ✔ 经继承
```

工程含义：跨模块传对象一律传**共同接口类型**（`packages/common` 里定义），不要依赖"字段长得一样"。

### A4 实例属性必须在声明处或构造函数里初始化

ArkTS 强制 `strictPropertyInitialization` 且无逃生门：字段要么带初始化器，要么在构造函数中赋值。`@ts-ignore`、关闭 strict（A33）、确定赋值断言 `!`（A5）都不可用。

```typescript
// ✗ 反例（ArkTS 禁止）
class Conn {
  public state: string;        // 声明处未初始化，构造函数也没赋值
  public id!: number;          // 用 `!` 压掉 strictPropertyInitialization
}

// ✓ 正例
class Conn {
  public state: string = 'idle';
  public id: number;
  constructor(id: number) { this.id = id; }
}
```

### A5 禁确定赋值断言 `let x!: T`

官方规则 `arkts-no-definite-assignment`（错误码 10605134，级别警告）。

```typescript
// ✗ 反例
let x!: number;
init(); function init(): void { x = 10; }

// ✓ 正例：声明即赋值（需要延迟的值改用可空类型 `number | null` 并判空）
let x: number = init(); function init(): number { return 10; }
```

### A6 禁参数属性（constructor 参数修饰符）

官方规则 `arkts-no-ctor-prop-decls`（错误码 10605025）。`constructor(private x: number)` 这种"声明+赋值合一"写法被禁，字段必须在 class 作用域显式声明。（本条同时是 Node type stripping 的硬错误，见 P1。）

```typescript
// ✗ 反例
class Person {
  constructor(private firstName: string, public age: number = 0) {}
}

// ✓ 正例
class Person {
  private firstName: string;
  public age: number;
  constructor(firstName: string, age: number = 0) {
    this.firstName = firstName;
    this.age = age;
  }
}
```

### A7 禁解构赋值

官方规则 `arkts-no-destruct-assignment`（错误码 10605069）。

```typescript
// ✗ 反例
let [one, two] = [1, 2];
[one, two] = [two, one];
[head, ...tail] = [1, 2, 3, 4];

// ✓ 正例：逐字段取值 + 临时变量
let one = arr[0]; let two = arr[1];
let tmp = one; one = two; two = tmp;
```

### A8 禁解构变量声明

官方规则 `arkts-no-destruct-decls`（错误码 10605074）。

```typescript
// ✗ 反例
let { x, y } = returnZeroPoint();

// ✓ 正例：先拿对象，再逐字段取
let zp = returnZeroPoint();
let x = zp.x; let y = zp.y;
```

### A9 禁函数参数解构

官方规则 `arkts-no-destruct-params`。

```typescript
// ✗ 反例
function dist({ x, y }: Point): number { return x + y; }

// ✓ 正例
function dist(p: Point): number { return p.x + p.y; }
```

### A10 禁运行时变更对象布局（增删属性、改属性类型）

ArkTS 概述级禁令：不能给对象添加属性/方法，不能删除属性，不能把不兼容类型的值赋给已有属性；`as any` 之类的绕行同样被禁。

```typescript
// ✗ 反例（ArkTS 全部编译错误）
let p2 = new Point(2, 2);
p2.z = 'Label';            // 添加属性
(p2 as any).z = 'Label';   // 绕行同样禁止
delete (p2 as any).x;      // 删除属性
p4.x = 'Hello!';           // 改变属性类型

// ✓ 正例：需要什么字段，先在 class/interface 里声明并初始化
class Point3D extends Point { public z: number = 0; }
```

### A11 禁 `delete` 运算符

官方规则 `arkts-no-delete`（错误码 10605107）。

```typescript
// ✗ 反例：delete obj.key;
// ✓ 正例：置空值（字段类型含 null 时）obj.key = null;
```

### A12 禁原型赋值 / 方法重赋值

官方规则 `arkts-no-prototype-assignment`（10605105）、`arkts-no-method-reassignment`（10605106）。

```typescript
// ✗ 反例
Point.prototype.toString = function (): string { return ''; }; // 函数表达式+原型赋值双禁
p.toString = (): string => '';   // 实例上重赋方法

// ✓ 正例：方法在 class 内定义，需要多态用继承
class Point { public toString(): string { return 'Point'; } }
```

### A13 禁 index signature

官方规则 `arkts-no-indexed-signatures`（错误码 10605017）。

```typescript
// ✗ 反例
interface StringArray { [index: number]: string }

// ✓ 正例：用数组或显式字段；动态键值集合用 Record（注意 A17 的 undefined 联合）
class X { public f: string[] = []; }
let ports: Record<string, number> = { 'a': 1 };
let v: number | undefined = ports['a'];
```

### A14 禁通过索引访问字段 `obj['field']`

官方规则 `arkts-no-props-by-index`（错误码 10605029）。只能点访问已声明/继承可见的字段；例外：`TypedArray`（含 `Uint8Array`）按下标取元素是允许的。

```typescript
// ✗ 反例
console.info(p['x']);            // 对象字段索引访问
console.info(p.unknownField);    // 未声明字段

// ✓ 正例
console.info(p.x);
let b = payload[0];              // payload: Uint8Array ✔
```

### A15 禁对象字面量用于类型声明

官方规则 `arkts-no-obj-literals-as-types`（错误码 10605049）。

```typescript
// ✗ 反例
let o: { n: number; s: string };

// ✓ 正例
interface T { n: number; s: string }
let o: T;
```

### A16 禁映射类型、条件类型、intersection 类型、索引访问类型、`this` 类型

官方规则 `arkts-no-mapped-types`、`arkts-no-conditional-types`、`arkts-no-intersection-types`（10605122）、`arkts-no-aliases-by-index`、`arkts-no-typing-with-this`。

```typescript
// ✗ 反例
type ReadonlyPartial<T> = { readonly [K in keyof T]?: T[K] };  // 映射类型
type A = B extends C ? D : E;                                  // 条件类型
type Combined = A | B & C;                                     // 交叉类型（A & B）
type Elem = List['items'];                                     // 索引访问类型
class Set2 { add(other: this): void {} }                       // this 类型

// ✓ 正例：手写展开、用继承替代交叉
interface Combined { a: string; b: number }
```

### A17 Utility Types 仅支持 `Partial`、`Required`、`Readonly`、`Record`

官方规则 `arkts-no-utility-types`（错误码 10605138）。`Pick/Omit/Exclude/Extract/ReturnType/Parameters/Awaited/NonNullable/…` 全部禁用；`Partial<T>` 的 T 必须是类/接口；`Record` 索引访问结果类型含 `undefined`。

```typescript
// ✗ 反例
type Keys = keyof Peer;                 // keyof 亦不可用于此类场景
function f(): ReturnType<typeof g> { … }
type Cfg = Omit<FullCfg, 'secret'>;

// ✓ 正例：手写接口；Record 取值必须按可能 undefined 处理
interface Cfg { host: string; port: number }
function getPort(m: Record<string, number>): number {
  const p = m['port'];
  return p === undefined ? 0 : p;
}
```

### A18 禁 `as const` 断言与字面量类型

官方规则 `arkts-no-as-const`（错误码 10605142）。**注意连带影响：字符串/数字字面量联合类型（`'ping' | 'pong'`）同样不可移植**——ArkTS 不支持字面量类型。enum 之外的"常量集合"要按下面正例建模。

```typescript
// ✗ 反例
let x = 'hello' as const;
let y = [10, 20] as const;
type MsgType = 'ping' | 'pong';          // 字面量类型联合，ArkTS 禁

// ✓ 正例：常量对象（显式 interface 类型，无方法）+ 运行时校验函数
interface MsgTypeE { Ping: string; Pong: string }
const MsgType: MsgTypeE = { Ping: 'ping', Pong: 'pong' };
function parseMsgType(v: string): string | null {
  return v === MsgType.Ping || v === MsgType.Pong ? v : null;
}
```

### A19 类型转换仅支持 `as T`

官方规则 `arkts-as-casts`（错误码 10605053）。不支持 `<T>expr` 语法；错误转换运行时抛 `ClassCastException`（不像 TS 静默 undefined）。

```typescript
// ✗ 反例
let c1 = <Peer>maybePeer;

// ✓ 正例
let c2 = maybePeer as Peer;
```

### A20 类型保护：用 `instanceof` / `as`，禁自定义谓词 `x is T`

官方规则 `arkts-no-is`（错误码 10605004）、`arkts-instanceof-ref-types`（部分支持：`instanceof` 左值需为引用类型）。

```typescript
// ✗ 反例
function isPeer(x: unknown): x is Peer { return 'id' in x; }

// ✓ 正例
function asPeer(x: Peer | null): Peer | null { return x instanceof Peer ? x : null; }
```

### A21 泛型实参无法推断时必须显式标注

官方规则 `arkts-no-inferred-generic-params`（错误码 10605045）。

```typescript
// ✗ 反例
let v = lookup('key');          // 泛型无法从上下文推断

// ✓ 正例
let v = lookup<number>('key');
```

### A22 函数形态限制：禁函数表达式、禁函数内嵌套函数声明

官方规则 `arkts-no-func-expressions`（10605046）、`arkts-no-nested-funcs`（10605044）。统一用箭头函数；需要"局部复用"时提升为模块级函数或类方法。

```typescript
// ✗ 反例
let f = function (s: string): void { console.info(s); };
function outer(): void { function inner(): void {} inner(); }

// ✓ 正例
let f = (s: string): void => { console.info(s); };
function helper(s: string): void {}
function outer2(): void { helper('x'); }
```

### A23 `this` 与函数对象限制

官方规则：`arkts-no-standalone-this`（独立 `this`）、`arkts-no-func-props`（函数声明属性）、`arkts-no-func-apply-call`（10605019）、`arkts-no-func-bind`（10605141）、`arkts-no-generators`（生成器函数）。

```typescript
// ✗ 反例
function f(this: Window): void {}             // 独立 this
const g = function (...): void {}; g.memo = {}; // 函数属性
f.apply(null, args); f.call(o); f.bind(o);    // apply/call/bind
function* gen(): Generator<number> { yield 1; }

// ✓ 正例：方法在类中；参数显式传；返回数组替代生成器
class Seq2 { public next(n: number): number[] { … } }
```

### A24 运算符与语句限制

官方规则：`arkts-no-for-in`（10605055）、`arkts-no-with`（10605056）、`arkts-no-in`（10605058）、`arkts-no-comma-outside-loops`、`arkts-no-polymorphic-unops`（一元 `+ - ~` 仅数值）、`arkts-no-type-query`（`typeof` 仅允许出现在表达式中，不能作类型）。

```typescript
// ✗ 反例
for (const k in obj) { … }        // for..in；遍历键用 Object.keys？见 §6-U5
if ('id' in peer) { … }           // in 运算符
let s: typeof x;                  // typeof 作类型
let t = +'42';                    // 一元 + 作用于字符串
let z = (a = 1, b = 2, a + b);    // 逗号运算符用于循环外
with (obj) { … }

// ✓ 正例
const keys: string[] = ['id', 'port'];
for (const k of keys) { … }       // for..of ✔
let n = Number('42');             // 显式转换
let q: number = x;
```

### A25 `throw` 只能抛 `Error` 及其派生类实例

官方规则 `arkts-limited-throw`（错误码 10605087）。

```typescript
// ✗ 反例
throw 4; throw 'bad'; throw { code: 1 };

// ✓ 正例
throw new Error('bad');
class WireError extends Error { public code: number = 0; }
throw new WireError();
```

### A26 `catch` 变量不允许类型标注

官方规则 `arkts-no-types-in-catch`（错误码未核对原文，见 §6-U9）。

```typescript
// ✗ 反例
try { … } catch (e: Error) { … }

// ✓ 正例
try { … } catch (e) { … }
```

### A27 展开运算符仅支持数组 / `Array` 子类 / `TypedArray`，且仅限两种场景

官方规则 `arkts-no-spread`（错误码 10605099）：① 传给剩余参数；② 把数组复制进数组字面量。**对象展开禁用**。

```typescript
// ✗ 反例
let p3 = { ...p2, z: 3 };                    // 对象展开
foo(...args);                                // args 为元组类型亦不保证可用

// ✓ 正例
let arr4 = [...arr1, 10, ...typedArr, 11];   // 数组/TypedArray 展开进字面量
logAll(numbers[0], numbers[1], numbers[2]);  // 或逐参传递
```

### A28 模块语法禁集

官方规则：`arkts-no-require`、`arkts-no-export-assignment`、`arkts-no-ambient-decls`（ambient module 声明）、`arkts-no-umd`、`arkts-no-import-assertions`、`arkts-no-module-wildcards`、`arkts-no-misplaced-imports`（import 必须位于其他语句之前）。

```typescript
// ✗ 反例
import mod = require('m');   // import 赋值
export = Foo;                // export 赋值
declare module 'm' { … }
const x = 1; import { y } from './y.ts';   // import 前有语句
import data from './d.json' with { type: 'json' };

// ✓ 正例：纯 ESM 具名/默认导入导出，import 全部置顶
import { y } from './y.ts';
export class Foo {}
```

### A29 `.ts` 不得 import `.ets`；`.ets` 可 import `.ts`

官方规则 `arkts-no-ts-deps`。核心库（.ts）永不依赖 .ets（见 §0）。

### A30 禁 `Symbol()`、`globalThis`、`new.target`

官方规则 `arkts-no-symbol`（10605031）、`arkts-no-globalthis`（10605032）、`arkts-no-new-target`。

```typescript
// ✗ 反例
const k = Symbol('k'); (globalThis as any).cache;   // as any 亦禁（A1/A10）
// ✓ 正例：模块级 const 常量；依赖用构造注入，不用全局单例
```

### A31 动态标准库 API 禁集

官方规则 `arkts-limited-stdlib`（错误码 10605144）：`eval`；`Object` 的 `__proto__/assign/create/defineProperty/defineProperties/freeze/seal/fromEntries/getPrototypeOf/setPrototypeOf/getOwnProperty*(…)/hasOwnProperty/is/preventExtensions` 等全部禁用；`Reflect` 全家禁用；`Proxy` handler 陷阱禁用。

```typescript
// ✗ 反例
Object.assign(defaults, cfg); Object.freeze(obj); Object.defineProperty(o, 'k', …);
Reflect.ownKeys(o); new Proxy(target, handler);

// ✓ 正例：字段逐个拷贝；冻结需求改为"只读接口"（A17 Readonly）
function withDefaults(cfg: Cfg): Cfg {
  const out: Cfg = { host: '0.0.0.0', port: 0 };
  if (cfg.host !== undefined) { out.host = cfg.host; }
  return out;
}
```

### A32 `ESObject` 类型受限

官方规则 `arkts-limited-esobj`（错误码 10605151）。核心库为纯 `.ts`，**不得使用 `ESObject`**（那是 .ets 侧跨语言场景的类型）。

### A33 禁 `@ts-ignore` / `@ts-nocheck`，strict 检查不可关闭

官方规则 `arkts-strict-typing-required`（错误码 10605146）。

```typescript
// ✗ 反例
// @ts-ignore
let s1: string = null;
// ✓ 正例
let s1: string | null = null;
```

### A34 `enum`：ArkTS 仅部分支持 → 本项目直接禁（见 P1）

官方仍保留的两条限制：`arkts-no-enum-mixed-types`（10605111，成员须同类型且为编译期常量，禁运行时表达式如 `Math.random()`）、`arkts-no-enum-merging`（10605113，禁声明合并）。叠加 Node strip-only 不支持 enum（P1），**本仓库一律不用 enum**，替代写法见 A18 正例。

```typescript
// ✗ 反例
enum Mode { A = 1, B = Math.random() }   // 双重违规
// ✓ 正例：A18 的常量对象模式，或纯数值常量表
interface ModeE { Dial: number; Listen: number }
const Mode: ModeE = { Dial: 1, Listen: 2 };
```

### A35 `namespace`：ArkTS 仅部分支持 → 本项目直接禁（见 P1）

官方限制：`arkts-no-ns-as-obj`（namespace 不能当对象用）、`arkts-no-ns-statements`（namespace 内禁非声明语句）。Node strip-only 全禁。**用 ES 模块替代**：一个文件一个模块，导出函数/类/常量。

```typescript
// ✗ 反例
export namespace Util { export const K = 3; }
// ✓ 正例
// util.ts
export const K: number = 3;
```

### A36 其他禁则速查（均来自官方规则表）

| 规则 | 内容 |
|---|---|
| `arkts-identifiers-as-prop-names` | 对象属性名必须是合法标识符 |
| `arkts-unique-names` | 类型/命名空间命名必须唯一 |
| `arkts-no-var` | 用 `let`/`const`，不用 `var` |
| `arkts-no-noninferrable-arr-literals` | 数组字面量元素必须可推断类型（混合类型数组须显式标注元素类型） |
| `arkts-no-private-identifiers` | 禁 `#` 私有字段（用 `private`） |
| `arkts-no-multiple-static-blocks` | 仅允许一个静态块 |
| `arkts-no-class-literals` | 禁类表达式 |
| `arkts-no-classes-as-obj` | class 不能被当对象用 |
| `arkts-implements-only-iface` | class 只能 `implements` 接口（不能 implements 类） |
| `arkts-extends-only-class` | 接口不能继承类 |
| `arkts-no-extend-same-prop` | 接口不能继承含相同方法的两个接口 |
| `arkts-no-call-signatures` / `arkts-no-ctor-signatures-type` / `arkts-no-ctor-signatures-iface` / `arkts-no-ctor-signatures-funcs` | 禁调用签名与构造签名（类型/接口/函数类型中） |
| `arkts-no-decl-merging` | 禁声明合并（接口合并、enum 合并等） |
| `arkts-no-jsx` | 禁 JSX |
| `arkts-no-implicit-return-types` | 限制省略函数返回类型标注：对外函数显式写返回类型 |
| `arkts-instanceof-ref-types` | `instanceof` 左值须为引用类型（原始类型先显式包装） |

---

## 2. 本项目硬性工程约束

以下为**仓库级强制**，比 ArkTS 官方规则更严或与其正交；所有 AI 开发者必须照办。

### P1 只用可擦除语法（erasable syntax）

Node 22 的 type stripping 只能"删类型"，不能"改语法"。**禁用**：`enum`、`namespace`（含 `module` 声明式用法）、构造函数参数属性、`import … = require(...)`、`export =`。

本机实测（Node v22.23.2，未加 flag 直接运行 `.ts`）：

```
$ node badenum.ts
SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]: TypeScript enum is not supported in strip-only mode

$ node badns.ts
SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]: TypeScript namespace declaration is not supported in strip-only mode

$ node badparam.ts        # constructor(private name: string)
SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]（指向 private 参数）
```

替代：enum/常量集 → A18 常量对象模式；namespace → ES 模块；参数属性 → A6 显式字段。编译期由 `erasableSyntaxOnly: true` 拒绝（T2）。

### P2 相对导入必须写 `.ts` 后缀

Node 直接跑 `.ts` 时按 ESM 精确解析 specifier，不做扩展名补全。本机实测：

```
$ node jsimport.ts        # import { Seq } from './erasable.js'
Error [ERR_MODULE_NOT_FOUND]: Cannot find module '...\erasable.js' imported from '...\jsimport.ts'

$ node main.ts            # import { Seq } from './erasable.ts'
peek= 2  clock= 0         # 正常
```

规则：所有**相对/同包内**导入写全 `./x.ts`、`../y/z.ts`（类型导入同样：`import { type Clock } from './clock.ts'`，配合 `verbatimModuleSyntax`）。包名导入（跨包 `@ohos-tailscale/common`）不涉及本条。

### P3 核心 src 禁 import 任何 Node API

- 范围：`packages/*/src/**/*.ts` 中所有**非测试**文件；
- 禁止：一切 `node:*` 内置模块（`node:fs/net/os/crypto/buffer/path/process`…）与 Node 全局（`process`、`Buffer`、`global`、`__dirname`、`__filename`、`require`）；
- 例外：`node:test` 与 `node:assert`（含 `node:assert/strict`）**只允许出现在 `*.test.ts` 文件**。

本机实测测试形态（Node v22.23.2）：

```
$ node --test pkg/clock.test.ts
# tests 1 / # pass 1 / # fail 0
$ node --test 'pkg/*.test.ts'    # glob 形式同样可用
```

```typescript
// pkg/clock.test.ts（唯一允许 node: 的文件形态）
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FixedClock, type Clock } from './clock.ts';
```

### P4 禁非确定来源：时钟与随机数由构造注入，接口放 common 包

核心 src **禁止**：`Date.now()`、无参 `new Date()`（读当前时刻）、`performance.now()`、`Math.random()`、`crypto.getRandomValues`/`crypto.webcrypto`/`crypto.randomBytes`、`process.hrtime*`、`process.uptime()`。从注入值构造日期（`new Date(ms)`、`new Date(iso)`）允许。

**接口定义放 `packages/common`**（两套实现：测试用确定性实现，真机用系统 API 包装），依赖一律构造函数注入：

```typescript
// packages/common/src/time.ts
export interface Clock {
  /** 挂钟毫秒（协议时间戳用） */
  wallMs(): number;
  /** 单调毫秒（超时、重传间隔计算用） */
  monotonicMs(): number;
}

// packages/common/src/random.ts
export interface RandomSource {
  /** 填充密码学安全随机字节；测试实现用确定性 PRNG，真机实现包装系统安全随机 */
  randomBytes(into: Uint8Array): void;
}
```

```typescript
// ✗ 反例
class NonceGen {
  nextNonce(): Uint8Array {
    return crypto.getRandomValues(new Uint8Array(12));   // 隐式全局+非确定，双违规
  }
}

// ✓ 正例
import { type RandomSource } from '@ohos-tailscale/common';
class NonceGen {
  private rng: RandomSource;                       // 显式字段（A6）
  constructor(rng: RandomSource) { this.rng = rng; }
  nextNonce(): Uint8Array {
    const n: Uint8Array = new Uint8Array(12);
    this.rng.randomBytes(n);
    return n;
  }
}
```

理由：① 测试可复现；② 真机迁移时只换 `packages/common` 的实现（Node 实现用 `node:crypto`，且**只允许出现在 common 的 node 实现文件中**——若追求核心零 Node 依赖，把平台实现放 `app/` 侧或独立 adapter 包，见 §6-U7）。

### P5 字节一律 `Uint8Array`

- 对外 API 签名统一 `Uint8Array`（及必要时的 `TypedArray` 家族）；**禁 `Buffer`** 与 `node:buffer`（`Buffer` 是 Node 专有全局，ArkTS 无）；
- 构造：`new Uint8Array(n)`、`Uint8Array.from(...)`；切片用 `subarray()`（注意视图共享底层内存，跨层传递需拷贝时用 `slice()`）；
- 底层存储可用 `ArrayBuffer`，但跨函数边界一律暴露 `Uint8Array`；
- 字符串↔字节编解码（UTF-8）、hex/base64：Node 的 `Buffer` 不可用，先收敛到 `packages/common` 的接口（可用性风险见 §6-U3/U4）。

```typescript
// ✗ 反例
const key: Buffer = Buffer.from(hex, 'hex');
// ✓ 正例
const key: Uint8Array = Uint8Array.from(bytes);
```

### P6 大整数一律 `BigInt`

- 涉及 > 2^53−1 的整数（WireGuard 会话计数器、字节数统计等）一律 `BigInt`，禁止用 `number` 冒充 64 位整数；
- `target: ES2022` 满足 BigInt 字面量（`0n`）要求；
- 注意：`JSON.stringify` 不能直接序列化 `BigInt`，序列化边界显式转 `string`/`number`；
- ArkTS 侧 BigInt 支持未真机验证（§6-U2），核心封装在窄接口后便于替换。

```typescript
// ✗ 反例
let counter: number = 9007199254740993;     // 精度已丢失
// ✓ 正例
let counter: bigint = 0n;
counter += 1n;
```

### P7 根 `package.json` 必须 `"type": "module"`

本机实测：`module: nodenext` + `verbatimModuleSyntax` 下，缺 `"type": "module"` 时全部 ESM 语法报错（TS1287/TS1295，见附录 A）；补上后只剩预期错误。`node --test` 与 type stripping 在 ESM 模式下行为一致。

---

## 3. tsconfig / package.json 基线（本机验证过，可直接抄）

### 3.1 根 `tsconfig.json`

```jsonc
{
  "compilerOptions": {
    "strict": true,                        // T1：ArkTS 强制严格检查（A33），本地同等强度
    "target": "ES2022",                    // T4：BigInt 字面量、最新类字段语义
    "module": "nodenext",                  // T3
    "moduleResolution": "nodenext",        // T3：与 Node 22 解析一致
    "allowImportingTsExtensions": true,    // T3：允许 .ts 后缀导入（P2）
    "noEmit": true,                        // T3：核心库不做本地产物，Node 直接跑源码
    "erasableSyntaxOnly": true,            // T2：编译期拒绝 enum/namespace/参数属性（P1）
    "verbatimModuleSyntax": true,          // T2：type 导入必须写 type，贴近 ArkTS 显式性
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true,
    "types": ["node"]                      // T4：供 node:test/assert 类型；需 devDependencies
  },
  "include": ["packages/**/*.ts"],         // T5：仅 packages（含测试）
  "exclude": ["app", "node_modules"]       // T5：HarmonyOS 工程壳与依赖不入主类型检查
}
```

约束条目：

- **T1** `strict: true` 必开，禁任何 `@ts-ignore/@ts-nocheck`（A33）。
- **T2** `erasableSyntaxOnly: true` 与 `verbatimModuleSyntax: true` 必开。本机 tsgo 7.0.2 实测：`erasableSyntaxOnly` 对 enum/namespace/参数属性分别报 `TS1294`；`verbatimModuleSyntax` 保证类型导入显式化。
- **T3** `module`/`moduleResolution` 用 `nodenext`，`allowImportingTsExtensions: true` + `noEmit: true` 成对出现。
- **T4** `types: ["node"]` 需要 `@types/node` 在 devDependencies；它把 Node 全局类型注入全部文件，**不构成**对 P3 的豁免——P3 靠代码评审 + §3.3 的 lint 门禁执行。
- **T5** `include` 仅 `packages/**`；`app/`、`node_modules` 排除（将来 app 工程由 DevEco 自己的 ets 配置管理）。

### 3.2 根 `package.json` 要点

```jsonc
{
  "name": "ohos-tailscale",
  "private": true,
  "type": "module",                                   // P7：实测必需
  "scripts": {
    "test": "node --test \"packages/**/*.test.ts\"",  // glob 实测可用
    "typecheck": "tsc --noEmit -p ."
  },
  "devDependencies": {
    "typescript": "^7.0.2",
    "@types/node": "^22.0.0"
  }
}
```

### 3.3 建议的 lint 门禁（P3/P4 的机器化执行）

`typescript-eslint` 规则示例（推荐入 CI，非本机已验证项）：

```jsonc
{
  "rules": {
    "no-restricted-imports": ["error", {
      "patterns": [{ "group": ["node:*", "node:buffer"], "message": "核心 src 禁 Node API；node:test/node:assert 仅限 *.test.ts" }]
    }],
    "no-restricted-globals": ["error", "process", "Buffer", "global", "__dirname", "__filename"],
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/no-unsafe-assignment": "error"
  },
  "overrides": [{ "files": ["**/*.test.ts"], "rules": { "no-restricted-imports": "off" } }]
}
```

---

## 4. 目录约定（承接 P2/P3/P4）

```
ohos-tailscale/
├─ package.json            # "type": "module"（P7）
├─ tsconfig.json           # §3.1 基线
├─ docs/arkts-constraints.md
├─ packages/
│  ├─ common/              # 纯接口与数据载体：Clock、RandomSource、消息/配置 interface（A2/A3/A4）
│  │  └─ src/*.ts          # 无任何平台依赖（P3/P4）
│  ├─ <protocol>/          # 协议核心：只 import common 与包名导入，禁 node:*（P3）、禁时钟/随机直读（P4）
│  └─ ...
└─ app/                    # HarmonyOS 工程壳（.ets），被 tsconfig 排除；.ets → import .ts 单向（§0）
```

跨包导入用包名（monorepo workspace），包内相对导入一律 `.ts` 后缀（P2）。

---

## 5. 当前仓库与基线的落地差距（写本文时的实测状态）

1. `package.json` **缺 `"type": "module"`**（P7 未满足）——按 §3.2 补齐；
2. `tsconfig.json` **缺 `erasableSyntaxOnly`、`verbatimModuleSyntax`**（T2 未满足）——按 §3.1 补齐；
3. `packages/` 目录尚未创建，§3 的类型检查验证是在结构等价的 `/tmp` 原型上完成的（附录 A）。

---

## 6. 不确定项（需 DevEco / 真机 / 后续验证，不得当既定规则执行）

> 编号说明：本节条目编号为 **U1–U10**；`README.md` 与 `DELIVERY_REPORT.md` 引述时加前缀称 **CU1–CU10**（与 `architecture.md` §10.2 的 AU* 前缀约定同理，避免与 AU 编号混淆）。下文 U2/U5/U6 即 CU2/CU5/CU6。

- **U1 规则文本来源差异**：本文件 ArkTS 禁则来自 `openharmony/docs` GitHub 镜像 `master` 分支（2026-09-28 抓取）。`developer.huawei.com` 在线版为 Angular SPA，`curl` 与无头抓取均只能取到页面外壳，无法比对正文；在线文档随 API 版本演进（如 `ESObject` 在 API 18 前后行为不同），发布前应对着 DevEco 内置文档核对一遍。
- **U2 `BigInt` 在 ArkTS/.ets 运行时的支持度**：官方指南未见专门章节，未在真机验证。若不支持，P6 的窄接口便于换成 `number`+进位或字符串编码方案。
- **U3 JS 全局 `TextEncoder`/`TextDecoder` 在 ArkTS 运行时的可用性**：`@ohos.util` 另有一套同名类且 API 不同。核心若需 UTF-8 编解码，先在 `packages/common` 定义 `TextCodec` 接口（P5 末条）。
- **U4 `btoa`/`atob`、`DataView`、`Blob` 等其他 Web API 的 ArkTS 可用性**：不在官方禁用清单（`arkts-limited-stdlib`）里，但"未禁"不等于"可用"，未真机验证前不要在核心直接使用，走 common 接口。
- **U5 `Object.keys()` 返回值在 ArkTS 的静态类型**：指南对 `Object` 静态方法大量禁用但未点名 `keys/entries/values`；其返回类型在 ArkTS 中如何标注（数组元素类型推断）未验证，遍历动态键的场景留待 DevEco 实测。
- **U6 ets loader 对 `.ts` 后缀 specifier 的解析**：`.ets` import `.ts` 源码是官方允许项（§0），但 hvigor/ArkTS 编译器是否接受 `./x.ts` 这种 nodenext 风格 specifier 未验证；迁移时可能需要在 app 侧做一层 `.ets` 适配文件。
- **U7 真机 `Clock`/`RandomSource` 平台实现**：HarmonyOS 侧安全随机（如 `@ohos.security.cryptoFramework`）与单调时钟 API 的确切签名、可用 API 版本未验证；实现放在 common 的平台适配文件或 `app/` 侧。
- **U8 测试链路迁移**：`node --test` 仅覆盖开发期；真机/CI 上的测试框架（hypium/xctest）与本套 `*.test.ts` 的复用方式未验证。
- **U9 错误码与告警级别漂移**：A 组各条错误码摘自镜像 `master`，DevEco 实际报错码随 API/编译器版本可能不同；以 lint 实际输出为准，规则名（`arkts-*`）更稳定。
- **U10 `Record` 索引访问返回 `T | undefined` 的 linter 实际行为**（A17）：官方文字如此，但未在 DevEco 中实际编译验证；写代码时按可空处理总是安全侧。

---

## 附录 A：本机验证记录（2026-09-28）

环境：win32，Node v22.23.2，TypeScript tsgo 7.0.2，@types/node 22.x；原型目录 `/tmp/arkts-probe`（`package.json` 含 `"type": "module"`，`tsconfig.json` 即 §3.1 基线，`include` 指向原型 `pkg/`）。

| # | 命令 | 结果 |
|---|---|---|
| 1 | `node --version` | `v22.23.2` |
| 2 | `node main.ts`（相对导入 `./erasable.ts`，未加 flag） | 正常输出（type stripping 默认可用） |
| 3 | `node jsimport.ts`（`./erasable.js` 指向 `.ts` 文件） | `ERR_MODULE_NOT_FOUND: ... erasable.js` → 证实 P2 |
| 4 | `node badenum.ts`（enum） | `SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]: TypeScript enum is not supported in strip-only mode` → P1 |
| 5 | `node badns.ts`（namespace） | 同上类错误 → P1 |
| 6 | `node badparam.ts`（参数属性） | 同上类错误（指向 `private` 参数）→ P1 |
| 7 | `node --test pkg/clock.test.ts` | `# pass 1 / # fail 0` → P3 测试形态可行 |
| 8 | `node --test 'pkg/*.test.ts'` | `# pass 1 / # fail 0` → glob 可用 |
| 9 | `npx tsc -p .`（无 `"type": "module"` 时） | 全文件 TS1287/TS1295 → 证实 P7 |
| 10 | `npx tsc -p .`（加 `"type": "module"` 后，含 enum/namespace/参数属性的 `bad.ts` 在场） | 仅 `bad.ts` 三处 `TS1294: This syntax is not allowed when 'erasableSyntaxOnly' is enabled` → 证实 T2/P1 的编译期拦截，其余文件零错误 |

官方文档抓取尝试记录（U1 依据）：`curl https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/typescript-to-arkts-migration` → HTTP 200 但仅 1,749 字节 `<app-root>` SPA 外壳；Gitee raw → 404；GitCode raw → 反爬 HTML 外壳；`https://raw.githubusercontent.com/openharmony/docs/master/zh-cn/application-dev/quick-start/typescript-to-arkts-migration-guide.md` → HTTP 200，99,951 字节（本文件规则来源）。
