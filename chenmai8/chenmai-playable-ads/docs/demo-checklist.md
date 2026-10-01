# 演示日检查单（上场前 30 分钟）与翻车兜底路径

> 来源：主路径接通复审（2026-09-29）给出的上场检查单与兜底路径，全文入库。
> 口径：所有命令在**仓库根**执行（本文件所在仓库）；python 一律用
> `python/.venv/Scripts/python.exe`，Node 用 PATH 中的 node。演示主路径 =
> 改 spec → `python -m pfcore make` → 二维码可扫（契约
> `docs/assets/specs/pipeline-contract.md` §5；留档实测走查总墙钟 28.9s，
> 硬预算 180s）。
>
> 原则：**宁可失败不可假绿**——任何检查项不过，先走兜底路径，不在场上修代码。

## 1. T-30 检查单（按序执行，每项都有客观判据）

### ① git 版本核对（1 分钟）

演示机上的工作树必须就是验证过的版本，不带未验证改动：

```bash
git status --short        # 判据：输出为空（无未提交/未跟踪的代码改动）
git log --oneline -1      # 判据：与跑过 gate_mainpath 全绿的 commit 一致（记下这行）
```

若不一致：先 `git stash -u` 或还原，重跑一遍 §①④ 再上场。

### ② 依赖自检（1 分钟）

```bash
python/.venv/Scripts/python.exe -c "import playwright, PIL, qrcode; print('deps OK')"
node --version
python/.venv/Scripts/python.exe --version
```

判据：`deps OK` + node v22.x + Python 3.12.x（与 gate 彩排同版本即可）。
任一 ImportError：现场不装依赖，直接走兜底路径 4（预构建 + U 盘）。

### ③ 防火墙预建规则（2 分钟，管理员 PowerShell/cmd；现场弹窗才想起来就晚了）

手机要能连本机伺服端口，先静态放行，避免演示中弹"允许访问"窗：

```powershell
# 预建（放行 8618/tcp 入站；换了 --serve-port 就同步改端口号）
netsh advfirewall firewall add rule name="pf-demo-http-8618" dir=in action=allow protocol=TCP localport=8618
# 核验规则在位
netsh advfirewall firewall show rule name="pf-demo-http-8618"
# 演示结束后删除（清理）
netsh advfirewall firewall delete rule name="pf-demo-http-8618"
```

判据：show 命令能列出该规则。局域网受限场地（会场 Wi-Fi 隔离）提前准备好
手机热点作备用网络（见兜底路径 2）。

### ④ gate 彩排（5–10 分钟，上场前最后一次全链路验证）

```bash
python scripts/gate_mainpath.py
```

判据：`GATE MAINPATH: PASS（5/5 项通过）`，exit 0。这一步同时把
`artifacts/demo-prebuilt/` 整体重建成"本次绿"的兜底目录（走查会真实跑
pfcore make 全流水线）。PASS 后**不再改任何代码**。

### ⑤ LAN IP 核验（1 分钟）

看走查/gate 输出的预览链接 `http://<IP>:8618/preview/...`：

```bash
ipconfig    # 核对链接里的 IP 确实是本机局域网网卡地址
```

判据：IP 与演示场局域网同网段（典型 192.168.x.x）。若是 198.18.x.x 之类
（VPN/TUN 虚拟网卡），手机扫不开——用 `--serve-host <局域网IP>` 显式指定重跑
走查，或 `python -m pfcore serve --host <IP>` 兜底伺服时指定。

### ⑥ 手机断网实测（2 分钟，验证"零外链"承诺）

手机**关闭蜂窝数据**（只留 Wi-Fi 或干脆飞行模式+Wi-Fi），扫
`artifacts/demo-prebuilt/qr.png`（或汇总页里的二维码）：

判据：游戏可完整加载并玩到结束页。产物是零外链自包含单 HTML（质检 CHK03
证据在渠道包旁的 `index.report.json`），断外网不影响游玩。

### ⑦ 人眼过一遍截图（2 分钟；自动判定 pass ≠ 观感合格）

CHK10 是机器判定（文案子串命中 + active+visible 采样核验 + 素材像素对账），
观感问题（文字截断/穿模/对比度/排版）机器不背锅。打开：

- `artifacts/<projectId>/<渠道>/<语言>/index.report.png`（竖屏）与
  `-landscape.png`（横屏）——质检实测截图；
- `artifacts/demo-prebuilt/index.html` 汇总页——二维码/渠道包/质检总表。

判据：人眼确认标题/教程/胜利/CTA/得分文案真的清晰上屏、替换素材看起来
正常、截图无空白与花屏。这就是"自动质检 + 人眼复核"双保险的最后一步。

### ⑧ 兜底伺服命令预演（30 秒，确认兜底目录真的能伺服）

```bash
python -m pfcore serve --root artifacts/demo-prebuilt --port 8618
```

判据：前台起伺服、打印二维码与预览链接；Ctrl+C 停止。这是演示日的
"不重跑流水线"兜底（伺服**已经生成好的**预构建产物，现场还会重建汇总页
与二维码）。

## 2. 翻车兜底路径（哪一步失败 → 切到什么）

按失败点对号入座，逐级降级，任何一级都能撑住演示：

### 兜底 1：现场 make/走查失败（质检 fail、打包失败、超预算）

→ **不现场修**。直接切"上次 gate 绿"的预构建产物：

```bash
python -m pfcore serve --root artifacts/demo-prebuilt --port 8618
```

演示内容变成"预构建产物走一遍"（汇总页 + 二维码 + 渠道包 + 质检报告都在
这个目录里，全部是 gate 彩排时的真实产物）。

### 兜底 2：二维码扫不出 / 手机打不开页面

按序排查（每步 30 秒）：

1. 防火墙规则在位？（§③ 的 show 命令）；伺服端口确实在听？
   `netstat -ano | findstr :8618`
2. 预览链接 IP 与手机网段同段？（§⑤）——不同段就
   `--serve-host <正确IP>` 重起；或 `--serve-port` 换口（如 8080，同步改防火墙规则）。
3. 会场 Wi-Fi 隔离（客户端互 ping 不通）？→ 手机开热点，演示机连手机热点，
   重跑伺服（此时预览链接的 IP 会变成热点网段）。

### 兜底 3：伺服进程没了 / 端口被占

`pfcore make` 的分离伺服器是后台进程，可能被清理软件误杀；状态文件
`.demo-serve.json` 带进程身份核实，失配会自动杀旧起新或顺延端口——但演示中
最稳的是前台重起：

```bash
python -m pfcore serve --root artifacts/demo-prebuilt --port 8618
```

前台进程死活可见；端口被占时它自己向后顺延（以它打印的链接为准重出二维码）。

### 兜底 4（终极）：本机 Python/依赖环境起不来

→ **U 盘兜底**：上场前把整个 `artifacts/demo-prebuilt/` 目录拷进 U 盘
（自包含：预览 HTML、渠道包、质检报告、二维码、汇总页，零外链零依赖）。
任何一台能开机的电脑（借的也行，不需要本仓库）：

```bash
python -m http.server 8618 --directory <U盘>/demo-prebuilt --bind 0.0.0.0
```

手机连同一网络扫 `qr.png`（二维码内容是演示机的 IP，换了机器/IP 后改扫
汇总页 `index.html` 里刷新出的二维码，或手机直接开
`http://<新IP>:8618/index.html`）。连 python 都没有的极端情况：任何静态
文件伺服器（如 VS Code Live Server、nginx）指向该目录等价可用——目录本身
就是纯静态件。

## 3. 上场节奏参考（五分钟脚本）

0:00 打开汇总页 `artifacts/demo-prebuilt/index.html`（计时/渠道表/质检总表）
0:40 现场改 spec 两处（标题→现场命题中文、seed+1）→ `python -m pfcore make`
1:10 讲解产物（渠道包大小/质检逐项），make 同时在跑（留档墙钟 28.9s）
1:45 二维码出现 → 手机扫码真机试玩（断网状态，§⑥ 已验证）
2:30 质检报告逐项过一遍（CHK01–CHK10），配合 §⑦ 人眼截图说明双保险
3:30+ 现场命题再跑一轮或展示渠道包内容（zip 单 HTML 均为真实产物）

> 演示中记住一条：**任何一步卡住，切兜底，不修码**。四条兜底路径覆盖
> 流水线失败/网络失败/进程失败/机器失败，预构建目录永远在手。
