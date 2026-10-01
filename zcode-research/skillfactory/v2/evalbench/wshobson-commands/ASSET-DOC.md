# ASSET-DOC — wshobson/commands（Claude Code 生产就绪 slash 命令集）

> 抓取日期：2026-09-29 ｜ 来源：https://github.com/wshobson/commands
> 原文存档：同目录 `_raw_README.md`（raw README.md 全文，20,972 字节 / 483 行，经 `curl https://raw.githubusercontent.com/wshobson/commands/main/README.md` 下载）
> 命令数量核实：经 GitHub Contents API 实测 `workflows/` 15 个文件、`tools/` 42 个文件，与 README 宣称的 57（15+42）一致。
> 许可：MIT。仓库页显示约 2.6k stars / 293 forks（2026-09-29 经 WebFetch 观察）。

## 1. 资产是什么

面向 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 的 **57 个生产就绪 slash 命令**合集，提供"智能自动化与多代理编排能力"。原文定位：

- **Workflows（15 个）**：多代理编排系统，协调跨领域的复杂多步操作
- **Tools（42 个）**：聚焦单一用途的专用工具

仓库顶层结构：`.github/`、`examples/`、`tools/`、`workflows/`、`README.md`、`LICENSE`。

## 2. 系统要求（原文）

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Git for repository management

## 3. 安装

> 原文注：本仓库使用 **slash commands** 模式；更现代的方式是 [Plugin Marketplace](https://github.com/wshobson/agents)（插件架构更干净）。

### 3.1 Slash Commands（本仓库方式）

```bash
# Navigate to Claude configuration directory
cd ~/.claude

# Clone the commands repository
git clone https://github.com/wshobson/commands.git
```

### 3.2 Plugin Marketplace（替代方式）

```bash
# Add the plugin marketplace
/plugin marketplace add https://github.com/wshobson/agents

# Install plugin collections
/plugin install claude-code-essentials
```

可用合集包括：`claude-code-essentials`、`full-stack-development`、`security-hardening`、`data-ml-pipeline`、`infrastructure-devops` 等。

## 4. 命令调用与参数机制

命令按 `tools/` 与 `workflows/` 目录组织，用**目录前缀**调用：

```bash
# Workflow invocation
/workflows:feature-development implement OAuth2 authentication

# Tool invocation
/tools:security-scan perform vulnerability assessment

# Multiple argument example
/tools:api-scaffold create user management endpoints with RBAC
```

### 免前缀用法（Alternative Setup, No Prefixes）

把 `.md` 文件复制到根目录即可直接调用：

```bash
cp tools/*.md .
cp workflows/*.md .

# Then invoke directly
/api-scaffold create REST endpoints
/feature-development implement payment system
```

### 参数机制（命令架构，原文）

每个 slash 命令是一个 markdown 文件：

| Component | Description | Example |
|-----------|-------------|---------|
| **Filename** | Determines command name | `api-scaffold.md` → `/tools:api-scaffold` |
| **Content** | Execution instructions | Agent prompts and orchestration logic |
| **Variables** | `$ARGUMENTS` placeholder | Captures and processes user input |
| **Directory** | Command category | `tools/` for utilities, `workflows/` for orchestration |

即：**参数就是命令后的自由文本**，经 `$ARGUMENTS` 占位符注入命令文件，无结构化 flags/选项。

### 安装后的文件组织（原文）

```
~/.claude/commands/
├── workflows/          # Multi-agent orchestration commands
│   ├── feature-development.md
│   ├── smart-fix.md
│   └── ...
├── tools/             # Single-purpose utility commands
│   ├── api-scaffold.md
│   ├── security-scan.md
│   └── ...
└── README.md          # This documentation
```

## 5. 全量命令清单

### 5.1 Workflows（15 个）

#### Core Development Workflows

| Command | Purpose | Agent Coordination |
|---------|---------|-------------------|
| `feature-development` | End-to-end feature implementation | Backend, frontend, testing, deployment |
| `full-review` | Multi-perspective code analysis | Architecture, security, performance, quality |
| `smart-fix` | Intelligent problem resolution | Dynamic agent selection based on issue type |
| `tdd-cycle` | Test-driven development orchestration | Test writer, implementer, refactoring specialist |

#### Process Automation Workflows

| Command | Purpose | Scope |
|---------|---------|-------|
| `git-workflow` | Version control process automation | Branching strategies, commit standards, PR templates |
| `improve-agent` | Agent optimization | Prompt engineering, performance tuning |
| `legacy-modernize` | Codebase modernization | Architecture migration, dependency updates, pattern refactoring |
| `multi-platform` | Cross-platform development | Web, mobile, desktop coordination |
| `workflow-automate` | CI/CD pipeline automation | Build, test, deploy, monitor |

#### Advanced Orchestration Workflows

| Command | Primary Focus | Specialized Agents |
|---------|---------------|-------------------|
| `full-stack-feature` | Multi-tier implementation | Backend API, frontend UI, mobile, database |
| `security-hardening` | Security-first development | Threat modeling, vulnerability assessment, remediation |
| `data-driven-feature` | ML-powered functionality | Data science, feature engineering, model deployment |
| `performance-optimization` | System-wide optimization | Profiling, caching, query optimization, load testing |
| `incident-response` | Production issue resolution | Diagnostics, root cause analysis, hotfix deployment |

### 5.2 Tools（42 个）

#### AI and Machine Learning (4 tools)

| Command | Functionality | Key Features |
|---------|--------------|--------------|
| `ai-assistant` | AI assistant implementation | LLM integration, conversation management, context handling |
| `ai-review` | ML code review | Model architecture validation, training pipeline review |
| `langchain-agent` | LangChain agent creation | RAG patterns, tool integration, memory management |
| `prompt-optimize` | Prompt engineering | Performance testing, cost optimization, quality metrics |

#### Agent Collaboration (3 tools)

| Command | Focus | Highlights |
|---------|-------|-----------|
| `multi-agent-review` | Multi-perspective code reviews | Architecture, security, and quality assessments |
| `multi-agent-optimize` | Coordinated performance optimization | Database, application, and frontend tuning |
| `smart-debug` | Assisted debugging | Root-cause analysis with performance-aware escalation |

#### Architecture and Code Quality (4 tools)

| Command | Purpose | Capabilities |
|---------|---------|--------------|
| `code-explain` | Code documentation | AST analysis, complexity metrics, flow diagrams |
| `code-migrate` | Migration automation | Framework upgrades, language porting, API migrations |
| `refactor-clean` | Code improvement | Pattern detection, dead code removal, structure optimization |
| `tech-debt` | Debt assessment | Complexity analysis, risk scoring, remediation planning |

#### Data and Database (3 tools)

| Command | Focus Area | Technologies |
|---------|------------|--------------|
| `data-pipeline` | ETL/ELT architecture | Apache Spark, Airflow, dbt, streaming platforms |
| `data-validation` | Data quality | Schema validation, anomaly detection, constraint checking |
| `db-migrate` | Database migrations | Schema versioning, zero-downtime strategies, rollback plans |

#### DevOps and Infrastructure (5 tools)

| Command | Domain | Implementation |
|---------|--------|----------------|
| `deploy-checklist` | Deployment preparation | Pre-flight checks, rollback procedures, monitoring setup |
| `docker-optimize` | Container optimization | Multi-stage builds, layer caching, size reduction |
| `k8s-manifest` | Kubernetes configuration | Deployments, services, ingress, autoscaling, security policies |
| `monitor-setup` | Observability | Metrics, logging, tracing, alerting rules |
| `slo-implement` | SLO/SLI definition | Error budgets, monitoring, automated responses |

#### Testing and Development (6 tools)

| Command | Testing Focus | Framework Support |
|---------|---------------|-------------------|
| `api-mock` | Mock generation | REST, GraphQL, gRPC, WebSocket |
| `api-scaffold` | Endpoint creation | CRUD operations, authentication, validation |
| `test-harness` | Test suite generation | Unit, integration, e2e, performance |
| `tdd-red` | Test-first development | Failing test creation, edge case coverage |
| `tdd-green` | Implementation | Minimal code to pass tests |
| `tdd-refactor` | Code improvement | Optimization while maintaining green tests |

#### Security and Compliance (3 tools)

| Command | Security Domain | Standards |
|---------|-----------------|-----------|
| `accessibility-audit` | WCAG compliance | ARIA, keyboard navigation, screen reader support |
| `compliance-check` | Regulatory compliance | GDPR, HIPAA, SOC2, PCI-DSS |
| `security-scan` | Vulnerability assessment | OWASP, CVE scanning, dependency audits |

#### Debugging and Analysis (4 tools)

| Command | Analysis Type | Output |
|---------|---------------|--------|
| `debug-trace` | Runtime analysis | Stack traces, memory profiles, execution paths |
| `error-analysis` | Error patterns | Root cause analysis, frequency analysis, impact assessment |
| `error-trace` | Production debugging | Log correlation, distributed tracing, error reproduction |
| `issue` | Issue tracking | Standardized templates, reproduction steps, acceptance criteria |

#### Dependency and Configuration Management (3 tools)

| Command | Management Area | Features |
|---------|-----------------|----------|
| `config-validate` | Configuration management | Schema validation, environment variables, secrets handling |
| `deps-audit` | Dependency analysis | Security vulnerabilities, license compliance, version conflicts |
| `deps-upgrade` | Version management | Breaking change detection, compatibility testing, rollback support |

#### Documentation and Collaboration (3 tools)

| Command | Documentation Type | Format |
|---------|-------------------|--------|
| `doc-generate` | API documentation | OpenAPI, JSDoc, TypeDoc, Sphinx |
| `pr-enhance` | Pull request optimization | Description generation, checklist creation, review suggestions |
| `standup-notes` | Status reporting | Progress tracking, blocker identification, next steps |

#### Operations and Context (4 tools)

| Command | Operational Focus | Use Case |
|---------|------------------|----------|
| `cost-optimize` | Resource optimization | Cloud spend analysis, right-sizing, reserved capacity |
| `onboard` | Environment setup | Development tools, access configuration, documentation |
| `context-save` | State persistence | Architecture decisions, configuration snapshots |
| `context-restore` | State recovery | Context reload, decision history, configuration restore |

## 6. 使用示例（原文 Usage Patterns）

### 功能实现

```bash
# Complete feature with multi-agent orchestration
/workflows:feature-development OAuth2 authentication with JWT tokens

# API-first development
/tools:api-scaffold REST endpoints for user management with RBAC

# Test-driven approach
/workflows:tdd-cycle shopping cart with discount calculation logic
```

### 调试与性能

```bash
# Intelligent issue resolution
/workflows:smart-fix high memory consumption in production workers

# Targeted error analysis
/tools:error-trace investigate Redis connection timeouts

# Performance optimization
/workflows:performance-optimization optimize database query performance
```

### 安全与合规

```bash
# Security assessment
/tools:security-scan OWASP Top 10 vulnerability scan

# Compliance verification
/tools:compliance-check GDPR data handling requirements

# Security hardening workflow
/workflows:security-hardening implement zero-trust architecture
```

### TDD 流程

```bash
# Complete TDD cycle with orchestration
/workflows:tdd-cycle payment processing with Stripe integration

# Manual TDD phases for granular control
/tools:tdd-red create failing tests for order validation
/tools:tdd-green implement minimal order validation logic
/tools:tdd-refactor optimize validation performance
```

### 命令组合策略

**顺序执行（Sequential Execution Pattern）：**

```bash
# Feature implementation pipeline
/workflows:feature-development real-time notifications with WebSockets
/tools:security-scan WebSocket implementation vulnerabilities
/workflows:performance-optimization WebSocket connection handling
/tools:deploy-checklist notification service deployment requirements
/tools:k8s-manifest WebSocket service with session affinity
```

**现代化改造管线（Modernization Pipeline）：**

```bash
# Legacy system upgrade
/workflows:legacy-modernize migrate monolith to microservices
/tools:deps-audit check dependency vulnerabilities
/tools:deps-upgrade update to latest stable versions
/tools:refactor-clean remove deprecated patterns
/tools:test-harness generate comprehensive test coverage
/tools:docker-optimize create optimized container images
/tools:k8s-manifest deploy with rolling update strategy
```

**完整功能开发管线（Integration Examples）：**

```bash
/workflows:feature-development user authentication system
/tools:security-scan authentication implementation
/tools:test-harness authentication test suite
/tools:docker-optimize authentication service
/tools:k8s-manifest authentication deployment
/tools:monitor-setup authentication metrics
```

## 7. 命令选择指南

### Workflow vs Tool 决策矩阵（原文）

| Criteria | Use Workflows | Use Tools |
|----------|--------------|-----------|
| **Problem Complexity** | Multi-domain, cross-cutting concerns | Single domain, focused scope |
| **Solution Clarity** | Exploratory, undefined approach | Clear implementation path |
| **Agent Coordination** | Multiple specialists required | Single expertise sufficient |
| **Implementation Scope** | End-to-end features | Specific components |
| **Control Level** | Automated orchestration preferred | Manual control required |

### Workflow 选择示例

| Requirement | Recommended Workflow | Rationale |
|-------------|---------------------|-----------|
| "Build complete authentication system" | `/workflows:feature-development` | Multi-tier implementation required |
| "Debug production performance issues" | `/workflows:smart-fix` | Unknown root cause, needs analysis |
| "Modernize legacy application" | `/workflows:legacy-modernize` | Complex refactoring across stack |
| "Implement ML-powered feature" | `/workflows:data-driven-feature` | Requires data science expertise |

### Tool 选择示例

| Task | Recommended Tool | Output |
|------|-----------------|--------|
| "Generate Kubernetes configs" | `/tools:k8s-manifest` | YAML manifests with best practices |
| "Audit security vulnerabilities" | `/tools:security-scan` | Vulnerability report with fixes |
| "Create API documentation" | `/tools:doc-generate` | OpenAPI/Swagger specifications |
| "Optimize Docker images" | `/tools:docker-optimize` | Multi-stage Dockerfile |

## 8. 执行最佳实践

### 上下文优化（原文 Context Optimization）

1. **Technology Stack Specification**: Include framework versions, database systems, deployment targets
2. **Constraint Definition**: Specify performance requirements, security standards, compliance needs
3. **Integration Requirements**: Define external services, APIs, authentication methods
4. **Output Preferences**: Indicate coding standards, testing frameworks, documentation formats

### 链式调用策略

1. **Progressive Enhancement**: Start with workflows for foundation, refine with tools
2. **Pipeline Construction**: Chain commands in logical sequence for complete solutions
3. **Iterative Refinement**: Use tool outputs as inputs for subsequent commands
4. **Parallel Execution**: Run independent tools simultaneously when possible

### 性能特征（Performance Considerations，原文）

- **Workflows 通常需要 30–90 秒**完成完整编排
- **Tools 执行 5–30 秒**完成聚焦操作
- 前置提供详细需求以减少迭代轮次
- 多会话项目使用 `context-save`/`context-restore` 保存上下文

## 9. 限制与故障排查（Troubleshooting Guide，原文）

| Issue | Cause | Resolution |
|-------|-------|------------|
| Command not recognized | File missing or misnamed | Verify file exists in correct directory |
| Slow execution | Normal workflow behavior | Workflows coordinate multiple agents (30-90s typical) |
| Incomplete output | Insufficient context | Provide technology stack and requirements |
| Integration failures | Path or configuration issues | Check file paths and dependencies |

性能优化建议（原文）：上下文缓存（`context-save`）、批量合并相关任务、已知问题用 Tools / 探索性问题用 Workflows、需求描述清晰以减少迭代。

## 10. 特色实现与集成生态（README「Featured Command Implementations」节）

- **TDD 套件**：`tdd-cycle`（workflow）+ `tdd-red`/`tdd-green`/`tdd-refactor`（tools）；框架支持 Jest, Mocha, PyTest, RSpec, JUnit, Go testing, Rust tests
- **安全与基础设施**：`security-scan`（SAST/DAST、依赖扫描、密钥检测）、`docker-optimize`（镜像典型缩减 50–90%）、`k8s-manifest`（HPA、NetworkPolicy、PodSecurityPolicy、service mesh ready）、`monitor-setup`（Prometheus/Grafana/告警规则）；安全工具集成：Bandit, Safety, Trivy, Semgrep, Snyk, GitGuardian
- **数据与数据库**：`db-migrate` 支持 PostgreSQL, MySQL, MongoDB, DynamoDB（blue-green、expand-contract、版本化 schema）；`data-pipeline`（Spark, Kafka, Airflow, dbt）；`data-validation`（Great Expectations, Pandera, 自定义校验器）；零停机模式：滚动迁移、feature flags、双写、backfill
- **性能与成本**：`performance-optimization`（全栈 profiling、查询优化、缓存、CDN）、`cost-optimize`（right-sizing、spot 实例、预留容量）

## 11. 相关资源与贡献

- 文档：Claude Code 官方文档 / Slash Commands Reference / Subagents Architecture（docs.anthropic.com）
- 仓库：[commands](https://github.com/wshobson/commands)（本资产）、[agents 插件市场](https://github.com/wshobson/agents)、[anthropics/claude-code](https://github.com/anthropics/claude-code)
- 新建命令规范（原文 Development Guidelines 摘要）：workflow 放 `workflows/`（定义多专家委派逻辑、错误回退、输出合并）；tool 放 `tools/`（单一用途、生产就绪代码生成、自动检测项目栈）；命名用小写连字符、描述性且简洁、动作清晰（如 `deps-upgrade` 而非 `dependencies`）
- Issues / PR：https://github.com/wshobson/commands/issues
- 许可：MIT License（见仓库 LICENSE 文件）

---

*本文件为抓取整理稿：章节结构与中文说明为整理者所加，命令清单、调用语法、示例代码块、参数机制、限制表均忠实保留 README 原文（存档于 `_raw_README.md`）。*
