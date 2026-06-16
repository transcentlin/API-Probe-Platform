# API 平台探测系统 — Web UI 管理界面实施方案

**版本**: v1.0
**日期**: 2026-06-15
**状态**: 已确认，待执行

---

## 目录

1. [项目背景与现状](#一项目背景与现状)
2. [已确认的技术决策](#二已确认的技术决策)
3. [High-Level 架构设计](#三high-level-架构设计)
4. [详细功能规划](#四详细功能规划)
   - 4.1 统一加密平台注册表
   - 4.2 FastAPI 后端 API 层
   - 4.3 评分系统与报告数据提取
   - 4.4 前端 UI（React + Vite）
   - 4.5 多用户认证系统
5. [安全架构：双层密钥体系](#五安全架构双层密钥体系)
6. [阶段划分与任务拆解](#六阶段划分与任务拆解)
7. [文件影响矩阵](#七文件影响矩阵)
8. [验证计划](#八验证计划)

---

## 一、项目背景与现状

### 1.1 系统简介

API 平台探测系统是一个自动化测试工具，用于评估各类 AI API 聚合平台的质量。系统通过 6 个阶段（Stage 0-5）对平台进行多维度探测：

- **Stage 0** — 预检查（连通性测试）
- **Stage 1** — API 格式检测（支持 8 种格式：OpenAI Chat/Text/Responses、Anthropic、Gemini、Ollama、Cohere、DashScope）
- **Stage 2** — 端点发现（模型列表获取）
- **Stage 2.5** — 模型可用性预检（快速筛选不可用模型）
- **Stage 3** — 能力探测（8 个探针：基础对话/流式/工具调用/视觉/JSON/推理/联网/多轮）
- **Stage 4** — 边界探测（max_tokens、context_length、rate_limit）
- **Stage 5** — 稳定性分析（多轮压力测试）

探测完成后生成 Markdown 格式的详细报告。

### 1.2 现有代码结构

```
api_probe_system/
├── config/
│   ├── user_config.yaml        # 平台配置 + 全局默认参数（platforms + defaults）
│   └── .env.enc                # 加密的 API Key 保险箱
├── core/
│   ├── adapters/
│   │   └── base.py             # FormatAdapter 协议 + 8 种格式适配器 + AdapterRegistry
│   ├── engine/
│   │   ├── engine.py           # ProbeEngine 探测引擎编排器
│   │   └── stages.py           # Stage 0-5 实现（v1.8）
│   ├── probes/
│   │   ├── basic_chat.py       # 基础对话探针
│   │   ├── streaming.py        # 流式探针
│   │   ├── tool_calling.py     # 工具调用探针
│   │   ├── vision.py           # 视觉探针
│   │   ├── json_mode.py        # JSON 模式探针
│   │   ├── reasoning.py        # 推理探针
│   │   ├── web_search.py       # 联网搜索探针
│   │   └── multi_turn.py       # 多轮对话探针
│   ├── analyzer.py             # ResultAnalyzer 结果分析器
│   ├── config.py               # ConfigManager + ConfigStore（从 YAML 读取配置）
│   ├── constants.py            # 全局常量（ProbeMode、FORMAT_*、ErrorCategory 等）
│   ├── error_taxonomy.py       # 错误分类
│   ├── models.py               # 数据模型（PlatformConfig、ProbeContext、各阶段产出）
│   ├── reporter.py             # ReportGenerator 报告生成器（v1.7，Markdown 输出）
│   ├── scheduler.py            # PlatformScheduler 多平台调度器（串行/并行）
│   ├── secret.py               # SecretResolver 密钥解析（${VAR} 引用 + 脱敏）
│   └── vault.py                # EnvVault 加密保险箱（Fernet + PBKDF2HMAC + Keychain）
├── data/
│   ├── db.py                   # SQLite 数据库管理器（4 表：platforms/sessions/stage_results/probe_requests）
│   └── repositories/
│       └── session.py          # 会话 + 阶段结果 Repository
├── tools/
│   └── manage_keys.py          # CLI 密钥管理工具（init/list/add/remove/reset/encrypt/decrypt）
├── tests/                      # 96 个单元测试
├── run.py                      # CLI 多平台调度入口（交互菜单/命令行参数）
└── requirements.txt            # 依赖清单
```

### 1.3 当前配置的双源问题

现有系统的平台配置分散在两个文件中，通过 `${VAR}` 间接引用关联：

```yaml
# user_config.yaml — 平台定义（名称 + URL 的 ${VAR} 占位）
platforms:
  - name: BlazeAI
    base_url: ${BlazeAI_BASE_URL}       # ← 引用 .env.enc 中的变量
    api_key: ${BlazeAI_API_KEY}         # ← 引用 .env.enc 中的变量
```

```
# .env.enc 解密后 — 实际的键值对
BlazeAI_BASE_URL=https://blazeai.boxu.dev/api
BlazeAI_API_KEY=blz_etPwwN7ks...
Groq_BASE_URL=https://api.groq.com/openai/v1
Groq_API_KEY=gsk_xxxx...
```

**痛点**：每次增减平台需同时修改两个文件，且 user_config.yaml 目前仅配置了 4 个平台，而 .env.enc 中有 10+ 个平台的密钥，两边不同步。

### 1.4 报告文件现状

报告存放在项目根目录的 `reports/` 目录下，文件名格式为 `{平台名}_探测报告_{YYMMDD_HHMM}.md`。报告已在 `.gitignore` 中排除。

报告结构包含：执行摘要 → 平台概览 → 模型可用性总览 → 推荐模型（Top 3） → 能力矩阵 → 问题统计 → 不可用模型分析 → 边界探测 → 稳定性分析 → 阶段失败记录 → 附录。

---

## 二、已确认的技术决策

| 决策项 | 确认方案 | 备注 |
|:---|:---|:---|
| **前端技术栈** | React + Vite | SPA 体验 + 组件复用 + 多用户扩展性 |
| **实时通信** | SSE (Server-Sent Events) | 需求全是单向推送，SSE 实现简单且自动重连 |
| **加密文件策略** | 双文件：`platforms.enc` + `user_config.yaml` | 敏感数据加密，非敏感默认参数可 Git 追踪 |
| **配置迁移** | 一次性合并，先回归测试再开发 UI | 合并 user_config.yaml(platforms) + .env.enc → platforms.enc |
| **主密码时机** | Phase 1 单用户：启动时终端/Keychain 解锁；Phase 5 多用户：用户登录密码 | |
| **密钥架构** | 双层密钥（DEK + KEK） | 改密码只需重新包裹 DEK，无需重加密数据 |
| **密码找回** | 注册时生成恢复密钥 | 用户自行保管 |
| **评分系统** | 预留接口，每次深度测试更新分数 | 具体评分规则之后讨论 |
| **横向对比** | 选中平台并行深度测试 → 各自生成报告 → 额外生成对比报告 | |
| **UI 设计** | 暗色「深空探测站」主题 + Glassmorphism | 科技感、微动画、响应式布局 |

---

## 三、High-Level 架构设计

### 3.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                       React SPA 前端                              │
│  ┌────────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │   主页面        │  │  对比模式     │  │  平台详情子页面        │ │
│  │   平台卡片网格  │  │  勾选 + 启动  │  │  报告 + 历史 + 测试    │ │
│  │   CRUD 弹窗     │  │  对比报告渲染  │  │  状态灯 + 阶段进度条   │ │
│  └───────┬────────┘  └──────┬───────┘  └──────────┬────────────┘ │
│          │                  │                      │              │
│          └──────────────────┼──────────────────────┘              │
│                             │  REST API + SSE                     │
└─────────────────────────────┼────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                      FastAPI 后端                                  │
│                                                                    │
│  ┌────────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ /api/platforms  │  │ /api/tests   │  │ /api/reports          │  │
│  │ CRUD + 评分     │  │ 启动/状态    │  │ 列表/下载/删除        │  │
│  └───────┬────────┘  └──────┬───────┘  └──────────┬────────────┘  │
│          │                  │                      │               │
│  ┌───────▼──────────────────▼──────────────────────▼────────────┐ │
│  │                  服务层（Service Layer）                       │ │
│  │  PlatformManager ← 平台 CRUD + 加密读写                       │ │
│  │  TestRunner ← 后台 asyncio Task + SSE 事件流                  │ │
│  │  PlatformScorer ← 评分计算（桩实现）                          │ │
│  │  ReportParser ← 从 Markdown 报告提取结构化数据                │ │
│  └───────────────────────────┬─────────────────────────────────┘ │
│                              │                                    │
│  ┌───────────────────────────▼─────────────────────────────────┐ │
│  │                    现有核心引擎（复用）                        │ │
│  │  ProbeEngine → Stage0~5 → ReportGenerator → Markdown 报告    │ │
│  └───────────────────────────┬─────────────────────────────────┘ │
│                              │                                    │
│  ┌───────────────────────────▼─────────────────────────────────┐ │
│  │                      数据层                                   │ │
│  │  platforms.enc ← 加密平台注册表（AES/Fernet + PBKDF2）        │ │
│  │  user_config.yaml ← 全局默认参数（明文，可 Git 追踪）         │ │
│  │  reports/ ← Markdown 报告文件                                 │ │
│  │  probe.db ← SQLite（探测会话、阶段结果、请求记录）            │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 请求流转示意

```
用户操作                  前端 React              后端 FastAPI              数据层
  │                         │                        │                       │
  │── 打开主页面 ──────────→│                        │                       │
  │                         │── GET /api/platforms ──→│                       │
  │                         │                        │── 解密 platforms.enc ─→│
  │                         │                        │←── 平台数据 ──────────│
  │                         │                        │── 扫描 reports/ ──────→│
  │                         │                        │←── 最新报告路径 ───────│
  │                         │                        │── 计算评分 ──────────→ │
  │                         │←── [平台列表+评分] ────│                       │
  │←── 渲染卡片网格 ────────│                        │                       │
  │                         │                        │                       │
  │── 点击「深度测试」────→ │                        │                       │
  │                         │── POST /api/tests/run ─→│                       │
  │                         │←── {test_id} ──────────│                       │
  │                         │── GET /api/tests/       │                       │
  │                         │   status/{test_id} ────→│                       │
  │                         │   (SSE 连接)            │── 启动 asyncio Task ──│
  │                         │                        │   运行 ProbeEngine     │
  │                         │←── event: stage=1 ─────│                       │
  │←── 状态灯亮黄 ──────────│                        │                       │
  │                         │←── event: stage=3 ─────│                       │
  │←── 进度条推进 ──────────│                        │                       │
  │                         │←── event: complete ────│                       │
  │←── 状态灯亮绿 ──────────│                        │                       │
  │←── 报告刷新 ────────────│                        │                       │
```

---

## 四、详细功能规划

### 4.1 统一加密平台注册表（PlatformManager）

#### 4.1.1 目标

将现有双源配置（`user_config.yaml` 的 `platforms:` 节 + `.env.enc`）合并为统一的 `platforms.enc` 加密文件，消除 `${VAR}` 间接引用层。

#### 4.1.2 platforms.enc 数据结构

加密前的 JSON 内容：

```json
{
  "platforms": [
    {
      "name": "BlazeAI",
      "base_url": "https://blazeai.boxu.dev/api",
      "api_key": "blz_etPwwN7ks...",
      "enabled": true,
      "notes": "M2 完整验证（8 个探针）",
      "website": "https://blazeai.boxu.dev",
      "hints": {
        "format": null,
        "models": null
      }
    },
    {
      "name": "Groq",
      "base_url": "https://api.groq.com/openai/v1",
      "api_key": "gsk_xxxx...",
      "enabled": true,
      "notes": "",
      "website": null,
      "hints": null
    }
  ]
}
```

加密方式：复用现有 `EnvVault` 的 Fernet + PBKDF2HMAC 体系（AES-128-CBC + HMAC-SHA256，200K 轮派生）。

#### 4.1.3 user_config.yaml 简化后

```yaml
# 全局默认配置（仅保留非敏感运行参数）
defaults:
  timeouts:
    fast_threshold_ms: 30000
    slow_threshold_ms: 60000
    connect_timeout_s: 10.0
  deep_probe:
    top_n: 3
```

`platforms:` 节完全移除。

#### 4.1.4 PlatformManager 类设计

文件路径：`api_probe_system/core/platform_manager.py`

```python
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from .vault import EnvVault

@dataclass
class PlatformEntry:
    """单个平台条目（解密后的内存表示）。"""
    name: str
    base_url: str
    api_key: str
    enabled: bool = True
    notes: str = ""
    website: str = ""
    hints: dict = field(default_factory=dict)

class PlatformManager:
    """统一加密平台注册表管理器。
    
    职责：
    1. 从 platforms.enc 解密加载平台数据
    2. 提供 CRUD 接口
    3. 修改后加密写回 platforms.enc
    4. 提供向 PlatformConfig（现有 Pydantic 模型）的转换
    """
    
    REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "platforms.enc"
    
    def __init__(self, master_password: str):
        self._master_password = master_password
        self._platforms: list[PlatformEntry] = []
        self._load()
    
    # ── CRUD ──
    def list_platforms(self, include_disabled: bool = True) -> list[PlatformEntry]: ...
    def get_platform(self, name: str) -> PlatformEntry: ...
    def add_platform(self, entry: PlatformEntry) -> None: ...
    def update_platform(self, name: str, updates: dict) -> None: ...
    def delete_platform(self, name: str) -> None: ...
    def toggle_platform(self, name: str, enabled: bool) -> None: ...
    
    # ── 加密读写 ──
    def _load(self) -> None: ...      # 解密 platforms.enc → self._platforms
    def _save(self) -> None: ...      # self._platforms → 加密写回 platforms.enc
    
    # ── 兼容层 ──
    def to_platform_config(self, entry: PlatformEntry) -> "PlatformConfig":
        """转换为现有引擎需要的 PlatformConfig 对象。"""
        from .models import PlatformConfig
        return PlatformConfig(
            name=entry.name,
            base_url=entry.base_url,
            api_key=entry.api_key,  # 直接明文，不再需要 ${VAR}
            notes=entry.notes,
            website=entry.website or None,
            hints=entry.hints or None,
        )
    
    def clear_password(self) -> None:
        """安全清除内存中的主密码。"""
        self._master_password = None
```

#### 4.1.5 迁移脚本

文件路径：`api_probe_system/tools/migrate_to_registry.py`

功能：
1. 读取现有 `user_config.yaml` 中的 `platforms:` 列表
2. 读取 `.env.enc` 中的所有键值对
3. 解析每个平台的 `${VAR}` 引用，匹配到实际值
4. 合并为 `PlatformEntry` 列表
5. 加密写入 `platforms.enc`
6. 修改 `user_config.yaml`，移除 `platforms:` 节
7. 支持 `--dry-run` 模式预览而不执行

#### 4.1.6 ConfigManager 改造

文件路径：`api_probe_system/core/config.py`

改造内容：
- `ConfigManager.__init__()` 新增 `platform_manager: PlatformManager` 参数
- `list_platforms()` 改为从 `PlatformManager` 获取，不再从 YAML 读取
- `get_platform()` 同上
- `resolve_api_key()` **移除**（密钥已在 PlatformEntry 中明文存在）
- `get_probe_timeouts()` 和 `get_deep_probe_top_n()` 不变（仍从 YAML 读取）

#### 4.1.7 run.py 改造

- `unlock_vault()` 改为初始化 `PlatformManager`
- `make_worker()` 不再调用 `resolve_api_key()` 和 `SecretResolver.resolve()`
- 平台信息直接从 `PlatformManager.to_platform_config()` 获取

---

### 4.2 FastAPI 后端 API 层

#### 4.2.1 目录结构

```
api_probe_system/web/
├── __init__.py
├── app.py                  # FastAPI 应用工厂 + CORS + 静态文件挂载
├── dependencies.py         # FastAPI 依赖注入（PlatformManager、TestRunner 单例）
├── schemas.py              # Pydantic 请求/响应 Schema
├── test_runner.py          # 后台测试执行管理器
├── routes/
│   ├── __init__.py
│   ├── platforms.py        # 平台 CRUD API
│   ├── tests.py            # 测试执行 + SSE 状态推送
│   └── reports.py          # 报告管理 API
└── static/                 # React 构建产物（npm build 后复制）
```

#### 4.2.2 API 端点清单

**平台管理 (`/api/platforms`)**

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|:---|:---|:---|:---|:---|
| GET | `/api/platforms` | 平台列表（含评分、Top5、概览） | — | `PlatformSummary[]` |
| POST | `/api/platforms` | 新增平台 | `PlatformCreate` | `PlatformSummary` |
| GET | `/api/platforms/{name}` | 单平台详情 | — | `PlatformDetail` |
| PUT | `/api/platforms/{name}` | 编辑平台 | `PlatformUpdate` | `PlatformSummary` |
| DELETE | `/api/platforms/{name}` | 删除平台 | — | `204` |
| PATCH | `/api/platforms/{name}/toggle` | 启用/禁用 | `{"enabled": bool}` | `PlatformSummary` |

**注意**：所有响应中的 `api_key` 字段都使用 `SecretResolver.mask()` 脱敏（如 `blz_...7ks`），前端永远拿不到明文。只有 `POST`（新增）和 `PUT`（编辑，可选）时请求体中才包含明文 API Key。

**测试执行 (`/api/tests`)**

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|:---|:---|:---|:---|:---|
| POST | `/api/tests/run` | 启动测试 | `TestRequest` | `{"test_id": "..."}` |
| POST | `/api/tests/compare` | 启动横向对比 | `TestRequest` | `{"test_id": "..."}` |
| GET | `/api/tests/status/{test_id}` | SSE 实时状态流 | — | `text/event-stream` |
| GET | `/api/tests/active` | 当前运行中的测试 | — | `TestStatus[]` |

**报告管理 (`/api/reports`)**

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|:---|:---|:---|:---|:---|
| GET | `/api/reports/{platform}` | 该平台所有历史报告列表 | — | `ReportSummary[]` |
| GET | `/api/reports/{platform}/latest` | 最新报告 Markdown 原文 | — | `{"content": "..."}` |
| GET | `/api/reports/{platform}/{filename}` | 下载指定报告文件 | — | `FileResponse` |
| DELETE | `/api/reports/{platform}/{filename}` | 删除指定报告 | — | `204` |

#### 4.2.3 请求/响应 Schema

文件路径：`api_probe_system/web/schemas.py`

```python
class PlatformSummary(BaseModel):
    """主页面平台卡片数据。"""
    name: str
    base_url: str
    api_key_masked: str          # 脱敏后的 API Key
    enabled: bool
    notes: str
    score: float | None          # 综合评分（0-10），未测试为 None
    availability_rate: float | None  # 可用率
    api_formats: list[str]       # 检测到的 API 格式列表
    top_models: list[str]        # Top 5 推荐模型名
    total_models: int | None     # 模型总数
    last_tested: str | None      # 最近测试时间
    test_status: str             # "idle" / "running" / "completed" / "error"

class PlatformDetail(PlatformSummary):
    """平台详情子页面数据（扩展主页卡片数据）。"""
    latest_report_content: str | None   # 最新报告 Markdown 原文
    report_history: list[ReportSummary] # 历史报告列表

class PlatformCreate(BaseModel):
    name: str                    # 平台名称，唯一
    base_url: str                # API 基础 URL
    api_key: str                 # API 密钥（明文，服务端加密存储）
    notes: str = ""
    website: str = ""

class PlatformUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None   # 可选更新 Key
    notes: str | None = None
    website: str | None = None

class TestRequest(BaseModel):
    platforms: list[str]         # 平台名列表
    mode: str = "standard"       # "standard" / "deep"

class TestStatus(BaseModel):
    test_id: str
    platforms: list[str]
    mode: str
    status: str                  # "pending" / "running" / "completed" / "error"
    started_at: str
    progress: dict               # {platform_name: {stage: int, status: str}}

class ReportSummary(BaseModel):
    filename: str
    platform: str
    created_at: str
    size_bytes: int
    mode: str | None
```

#### 4.2.4 TestRunner（后台测试执行管理器）

文件路径：`api_probe_system/web/test_runner.py`

```python
class TestRunner:
    """管理后台测试任务的生命周期。
    
    核心机制：
    1. start_test() 启动 asyncio Task 在后台执行探测
    2. 探测过程中的阶段变更通过 asyncio.Queue 推送事件
    3. stream_events() 从 Queue 消费事件，生成 SSE 数据流
    """
    
    def __init__(self, platform_manager: PlatformManager, config_manager: ConfigManager):
        self._pm = platform_manager
        self._cm = config_manager
        self._active_tests: dict[str, TestTask] = {}
    
    async def start_test(self, platforms: list[str], mode: str) -> str:
        """启动单平台或多平台测试。
        
        1. 生成 test_id（UUID）
        2. 创建 asyncio.Queue 用于事件推送
        3. 创建 asyncio.Task 在后台执行
        4. 返回 test_id
        """
        ...
    
    async def start_comparison(self, platforms: list[str], mode: str = "deep") -> str:
        """启动横向对比测试。
        
        1. 对所有选中平台并行执行深度测试
        2. 等待所有平台完成
        3. 基于各自的测试报告，生成一份横向对比报告
        4. 通过 SSE 推送每个平台的进度 + 最终对比报告路径
        """
        ...
    
    async def stream_events(self, test_id: str) -> AsyncGenerator[dict, None]:
        """SSE 事件流生成器。
        
        事件格式：
        - {"event": "progress", "data": {"platform": "X", "stage": 2, "status": "running"}}
        - {"event": "platform_complete", "data": {"platform": "X", "report_path": "..."}}
        - {"event": "complete", "data": {"all_reports": [...], "comparison_report": "..."}}
        - {"event": "error", "data": {"platform": "X", "message": "..."}}
        """
        ...
```

`TestRunner` 内部复用现有 `run.py` 中的 worker 逻辑，关键改造点：

- 将 `run.py` 的 `make_worker()` 闭包提取为独立的 `async def run_platform_probe(...)` 函数
- 新函数接收 `PlatformConfig`、`mode`、`reports_dir` 等参数，不再依赖闭包
- `TestRunner` 和 CLI `run.py` 共用这个函数
- 在函数中插入事件回调（如 `on_stage_start(stage_num)`）用于 SSE 推送

#### 4.2.5 SSE 端点实现

```python
# web/routes/tests.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.get("/status/{test_id}")
async def test_status_stream(test_id: str):
    """SSE 端点：推送测试进度事件。"""
    test_runner = get_test_runner()
    
    async def event_generator():
        async for event in test_runner.stream_events(test_id):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
```

---

### 4.3 评分系统与报告数据提取

#### 4.3.1 PlatformScorer（评分引擎桩）

文件路径：`api_probe_system/core/scoring.py`

```python
@dataclass
class PlatformScore:
    """平台综合评分结果。"""
    overall: float              # 综合评分 0-10
    availability: float         # 可用性分项 0-10
    performance: float          # 性能分项 0-10
    capability: float           # 能力覆盖分项 0-10
    stability: float            # 稳定性分项 0-10（deep 模式才有）
    top_models: list[str]       # Top 5 推荐模型
    api_formats: list[str]      # 检测到的 API 格式
    total_models: int           # 模型总数
    available_models: int       # 可用模型数
    last_tested: datetime       # 最近测试时间

class PlatformScorer:
    """平台综合评分引擎。
    
    当前为桩实现，具体评分规则后续讨论。
    评分在每次深度测试完成后自动更新。
    """
    
    def score_from_context(self, ctx: ProbeContext) -> PlatformScore:
        """从探测上下文直接计算评分（测试完成时调用）。"""
        # 桩实现：基于可用率的简单评分
        ...
    
    def score_from_report(self, report_path: Path) -> PlatformScore:
        """从已有报告文件提取数据并计算评分。"""
        parser = ReportParser()
        parsed = parser.parse(report_path)
        return self._calculate(parsed)
```

评分在每次**深度测试**完成后自动计算并缓存（写入 SQLite 的 `platform_scores` 表或单独的 JSON 文件）。

#### 4.3.2 ReportParser（报告解析器）

文件路径：`api_probe_system/core/report_parser.py`

职责：从现有 Markdown 报告中提取结构化数据（用于首次加载已有报告的评分）。

```python
@dataclass
class ParsedReport:
    """从 Markdown 报告解析出的结构化数据。"""
    platform_name: str
    mode: str                    # quick / standard / deep
    generated_at: datetime
    availability_rate: float     # 可用率百分比
    total_models: int
    available_models: int
    api_formats: list[str]       # 检测到的 API 格式
    top_models: list[str]        # 推荐模型列表（从报告第三章提取）
    avg_latency_ms: float | None # 平均首字节延迟

class ReportParser:
    """Markdown 报告结构化解析器。"""
    
    def parse(self, report_path: Path) -> ParsedReport:
        """解析报告文件，提取关键指标。"""
        content = report_path.read_text(encoding="utf-8")
        # 1. 从标题行提取平台名
        # 2. 从「平台概览」表格提取 base_url、api_formats
        # 3. 从「模型可用性总览」提取 total/available
        # 4. 从「推荐模型」提取 top models
        # 5. 从「执行摘要」提取可用率
        ...
    
    def find_latest_report(self, platform_name: str, reports_dir: Path) -> Path | None:
        """查找指定平台的最新报告文件。"""
        pattern = f"{platform_name}_探测报告_*.md"
        reports = sorted(reports_dir.glob(pattern), reverse=True)
        return reports[0] if reports else None
```

#### 4.3.3 横向对比报告生成器

文件路径：`api_probe_system/core/comparison_reporter.py`

```python
class ComparisonReportGenerator:
    """横向对比报告生成器。
    
    输入：多个平台各自的 ProbeContext（或 ParsedReport）
    输出：一份 Markdown 对比报告
    """
    
    def generate(self, platform_data: list[ParsedReport]) -> str:
        """生成横向对比 Markdown 报告。
        
        报告结构：
        1. 对比摘要（雷达图数据 / 排名表）
        2. 模型可用率对比
        3. 性能（延迟）对比
        4. API 格式覆盖对比
        5. 能力覆盖对比
        6. 各平台分项评分对比表
        """
        ...
```

---

### 4.4 前端 UI（React + Vite）

#### 4.4.1 项目初始化

```bash
# 在 api_probe_system/ 下创建 React 项目
cd api_probe_system
npx -y create-vite@latest frontend --template react
cd frontend
npm install
```

构建产物目录：`api_probe_system/frontend/dist/`
FastAPI 通过 `StaticFiles` 挂载：`app.mount("/", StaticFiles(directory="frontend/dist", html=True))`

开发时前端独立启动（Vite dev server port 5173），通过 proxy 转发 API 请求到 FastAPI (port 8080)。

#### 4.4.2 组件结构

```
frontend/src/
├── main.jsx                # 入口
├── App.jsx                 # 根组件 + React Router
├── api/
│   └── client.js           # 统一 API 客户端（fetch 封装 + SSE 管理）
├── components/
│   ├── Layout.jsx           # 页面布局（顶部导航 + 内容区）
│   ├── PlatformCard.jsx     # 平台卡片（评分环 + 进度条 + Top 模型）
│   ├── ScoreRing.jsx        # 圆环评分动画组件
│   ├── StatusIndicator.jsx  # 状态指示灯（空闲/运行/完成/出错）
│   ├── StageProgress.jsx    # 阶段进度条（S0-S5）
│   ├── PlatformModal.jsx    # 新增/编辑平台弹窗
│   ├── CompareBar.jsx       # 底部浮动对比栏
│   ├── ReportViewer.jsx     # Markdown 报告渲染组件
│   └── ReportHistory.jsx    # 历史报告列表 + 下载/删除
├── pages/
│   ├── HomePage.jsx         # 主页面（平台卡片网格 + 对比模式）
│   └── PlatformPage.jsx     # 平台详情子页面（报告 + 测试 + 历史）
├── hooks/
│   ├── useSSE.js            # SSE 连接 Hook
│   └── usePlatforms.js      # 平台数据 Hook（含 CRUD）
└── styles/
    └── index.css            # 全局样式（设计系统）
```

#### 4.4.3 UI 设计规范

**主题：「深空探测站」(Deep Space Probe Station)**

| 设计 Token | 值 |
|:---|:---|
| **背景** | 线性渐变 `#0a0e1a` → `#111827`，叠加微弱网格纹理 |
| **卡片** | `background: rgba(255,255,255,0.05)`, `backdrop-filter: blur(12px)`, `border: 1px solid rgba(255,255,255,0.1)`, 悬浮时 `box-shadow` 发光上浮 |
| **主色** | `#3b82f6` (电蓝色) |
| **辅色** | `#06b6d4` (青色)，`#8b5cf6` (紫色) |
| **成功色** | `#10b981` (翠绿) |
| **警告色** | `#f59e0b` (琥珀) |
| **错误色** | `#ef4444` (鲜红) |
| **文字** | 主文字 `#f1f5f9`，次要 `#94a3b8`，弱化 `#64748b` |
| **字体** | `Inter`（英文/数字）+ `Noto Sans SC`（中文），`font-weight: 400/500/600/700` |
| **圆角** | 卡片 `16px`，按钮 `8px`，输入框 `8px` |
| **动画** | 卡片入场 `fadeInUp 0.4s ease-out`，评分环 `strokeDashoffset transition 1.5s`，状态灯脉冲 `pulse 2s infinite` |

**主页面布局**：
- 顶部导航栏：Logo + 标题 "API Probe Station" + [添加平台] 按钮 + 用户头像（多用户时）
- 中间：3 列响应式卡片网格（桌面 3 列 → 平板 2 列 → 手机 1 列）
- 卡片按评分降序排列；未测试的平台排在最后，显示灰色占位
- 每张卡片含：评分圆环、平台名、可用率进度条、API 格式标签、Top 5 模型、编辑/删除按钮、对比勾选框
- 底部浮动对比栏：选中 ≥2 个平台时滑入，显示已选数量 + "开始横向对比" 按钮

**平台详情子页面**：
- 面包屑导航：`API Probe Station > {平台名}`
- 上方分两栏：左侧为评分大圆环 + 分项指标；右侧为操作面板（基本测试/深度测试按钮 + 状态灯 + 阶段进度条 S0-S5）
- 中间：最新报告渲染区（Markdown → HTML，表格/代码块/emoji 美化）
- 下方：历史报告表格（文件名、日期、大小、下载/删除按钮）

**报告渲染增强**：
- 使用 `react-markdown` + `remark-gfm` 渲染 Markdown
- 表格：暗色条纹、hover 行高亮、固定表头
- 执行摘要区域：提取为独立指标卡片（平台健康度、可用率、推荐首选）
- 状态 emoji（🟢🔴🟡）替换为 SVG 图标
- 超长模型列表自动折叠（显示前 5 个 + "展开更多"）

---

### 4.5 多用户认证系统（Phase 5）

> 此 Phase 在前 4 个 Phase 稳定后再开发。以下为架构设计，确保前期实现预留正确的扩展接口。

#### 4.5.1 双层密钥体系

```
                    用户密码（用户记忆，不存储原文）
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
    auth_hash = bcrypt(pw)    KEK = PBKDF2(pw, user_salt)
    存入 users 表                     │
    用于登录验证                       ▼
                              解密 wrapped_dek
                                      │
                                      ▼
                              DEK（Data Encryption Key）
                              随机生成，注册时一次性产生
                                      │
                              ┌───────┴───────┐
                              ▼               ▼
                    加密 platforms_{uid}.enc    被 KEK 包裹存入 DB
                    (用户的平台数据)            (wrapped_dek)
                                              同时被 恢复密钥的 KEK 包裹
                                              (wrapped_dek_recovery)
```

#### 4.5.2 密码修改流程

```
1. 用旧密码 → 派生旧 KEK → 解包 wrapped_dek → 拿到 DEK
2. 用新密码 → 派生新 KEK → 重新包裹 DEK → 更新 wrapped_dek
3. 更新 auth_hash = bcrypt(新密码)
4. platforms_{uid}.enc 完全不需要动（DEK 没变）
```

#### 4.5.3 恢复密钥流程

注册时：
```
1. 生成 recovery_key = 随机 32 字符 Base62 字符串（只显示一次，让用户抄写）
2. 计算 KEK_recovery = PBKDF2(recovery_key, recovery_salt)
3. wrapped_dek_recovery = encrypt(DEK, KEK_recovery)
4. 存入 users 表
```

找回密码时：
```
1. 用户输入 recovery_key
2. 从 DB 取出 recovery_salt → 派生 KEK_recovery → 解包 wrapped_dek_recovery → 拿到 DEK
3. 用户设新密码 → 派生新 KEK → 重新包裹 DEK → 更新 wrapped_dek + auth_hash
4. 数据完整恢复 ✅
```

#### 4.5.4 用户数据库 Schema

```sql
CREATE TABLE users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT UNIQUE NOT NULL,
    auth_hash             TEXT NOT NULL,           -- bcrypt(password)
    user_salt             BLOB NOT NULL,           -- 16 字节，派生 KEK 用
    wrapped_dek           BLOB NOT NULL,           -- DEK 被 KEK 加密后
    recovery_salt         BLOB NOT NULL,           -- 16 字节，派生恢复 KEK 用
    wrapped_dek_recovery  BLOB NOT NULL,           -- DEK 被恢复 KEK 加密后
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login            TIMESTAMP
);
```

#### 4.5.5 Session 缓存与密钥生命周期

```python
class SessionKeyCache:
    """用户 Session 中的加密密钥缓存。"""
    
    # {user_id: (dek_bytes, expiry_time)}
    _cache: dict[int, tuple[bytes, float]] = {}
    TTL = 30 * 60  # 30 分钟超时
    
    def store(self, user_id: int, dek: bytes) -> None: ...
    def get(self, user_id: int) -> bytes | None: ...      # 过期返回 None
    def clear(self, user_id: int) -> None: ...             # 登出时调用
    def clear_expired(self) -> None: ...                   # 定时清理
```

#### 4.5.6 JWT 认证

```python
# 登录成功 → 签发 JWT
token = jwt.encode({"user_id": user.id, "exp": now + timedelta(hours=24)}, SECRET_KEY)

# 每个 API 请求 → 验证 JWT
@app.middleware("http")
async def auth_middleware(request, call_next):
    if request.url.path.startswith("/api/"):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        payload = jwt.decode(token, SECRET_KEY)
        request.state.user_id = payload["user_id"]
    return await call_next(request)
```

---

## 五、安全架构：双层密钥体系

（详见 §4.5，此处为总结图）

```
┌─────────────────────────────────────────────────────┐
│                  用户输入密码                         │
│                      │                               │
│         ┌────────────┴────────────┐                  │
│         ▼                         ▼                  │
│   bcrypt(password)          PBKDF2(password,          │
│   → auth_hash               user_salt)               │
│   存入 DB                   → KEK                    │
│   用于登录验证              (Key Encryption Key)      │
│                                  │                   │
│                         解密 wrapped_dek             │
│                                  │                   │
│                                  ▼                   │
│                         DEK (Data Encryption Key)    │
│                         注册时一次生成，永不变化       │
│                                  │                   │
│                    ┌─────────────┴──────────────┐    │
│                    ▼                            ▼    │
│          加密/解密                       被两种 KEK   │
│          platforms_{uid}.enc            包裹后存 DB   │
│          (用户的平台数据)                             │
│                                                      │
│   改密码 → 只重新包裹 DEK，数据文件不动               │
│   恢复密钥 → 用另一个 KEK 解包 DEK                    │
└──────────────────────────────────────────────────────┘
```

---

## 六、阶段划分与任务拆解

### 6.0 总体阶段依赖图

```
Phase 1 ──────→ Phase 2 ──────→ Phase 4 ──────→ Phase 6
(统一注册表)    (后端 API)       (前端 UI)        (集成验证)
                    │                                │
                    ├──→ Phase 3 ─────────────→──────┘
                    │    (评分+报告解析)
                    │
                    └──→ Phase 5 ─────────────→──────┘
                         (多用户认证，可延后)
```

### Phase 1：统一加密平台注册表（基础设施）

**目标**：合并双源配置 → platforms.enc，确保现有 CLI 功能正常。

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 1.1 | 实现 `PlatformManager` 类（CRUD + 加密读写 + PlatformConfig 转换） | — | `core/platform_manager.py` |
| 1.2 | 编写 `PlatformManager` 单元测试（CRUD、加密/解密、边界情况） | 1.1 | `tests/test_platform_manager.py` |
| 1.3 | 实现迁移脚本 `migrate_to_registry.py`（读旧配置 → 写新注册表） | 1.1 | `tools/migrate_to_registry.py` |
| 1.4 | 改造 `ConfigManager`：平台列表改从 `PlatformManager` 获取 | 1.1 | `core/config.py` (MODIFY) |
| 1.5 | 改造 `run.py`：使用 `PlatformManager` 替代 `SecretResolver` | 1.1, 1.4 | `run.py` (MODIFY) |
| 1.6 | 提取 `run_platform_probe()` 为独立可复用函数 | 1.5 | `core/probe_runner.py` (NEW) |
| 1.7 | 精简 `user_config.yaml`：移除 `platforms:` 节 | 1.3 | `config/user_config.yaml` (MODIFY) |
| 1.8 | 执行迁移脚本，生成 `platforms.enc` | 1.3, 1.7 | `config/platforms.enc` (NEW) |
| 1.9 | **回归测试**：运行全部 96 个单元测试 + CLI 端到端测试 | 1.4-1.8 | 测试报告 |

**Phase 1 完成标准**：
- `python run.py --all` 能正常运行，与合并前行为一致
- `python run.py --platforms BlazeAI --mode deep` 生成报告
- 96 个单元测试全部通过
- `platforms.enc` 存在且可正确解密

---

### Phase 2：FastAPI 后端 API 层

**目标**：搭建 Web 后端，暴露平台 CRUD / 测试执行 / 报告管理的 REST API。

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 2.1 | 创建 `web/` 包结构 | Phase 1 | `web/__init__.py`, `web/routes/__init__.py` |
| 2.2 | 实现 `web/schemas.py`（请求/响应 Pydantic 模型） | — | `web/schemas.py` |
| 2.3 | 实现 `web/dependencies.py`（PlatformManager / ConfigManager 单例注入） | 1.1 | `web/dependencies.py` |
| 2.4 | 实现 `web/routes/platforms.py`（平台 CRUD 全部 6 个端点） | 2.2, 2.3 | `web/routes/platforms.py` |
| 2.5 | 实现 `web/routes/reports.py`（报告列表/下载/删除/最新内容） | 2.2 | `web/routes/reports.py` |
| 2.6 | 实现 `web/test_runner.py`（后台 asyncio Task + 事件队列） | 1.6 | `web/test_runner.py` |
| 2.7 | 实现 `web/routes/tests.py`（测试启动 + SSE 状态推送） | 2.6 | `web/routes/tests.py` |
| 2.8 | 实现 `web/app.py`（FastAPI 应用工厂 + CORS + 路由挂载） | 2.4-2.7 | `web/app.py` |
| 2.9 | 实现 `run_web.py`（Web 入口脚本：终端解锁 → 启动 Uvicorn） | 2.8 | `run_web.py` |
| 2.10 | 编写 API 集成测试（使用 FastAPI TestClient） | 2.4-2.7 | `tests/test_web_api.py` |

**Phase 2 完成标准**：
- `python run_web.py` 启动成功，所有 API 端点可通过 curl/Postman 访问
- 平台 CRUD 正确操作 `platforms.enc`
- 测试启动后 SSE 正确推送阶段进度
- 现有 CLI `python run.py` 仍正常工作（未被破坏）

---

### Phase 3：评分系统 + 报告数据提取

**目标**：实现从报告中提取结构化数据 + 评分桩接口 + 横向对比报告生成。

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 3.1 | 实现 `ReportParser`（从 Markdown 报告提取结构化数据） | — | `core/report_parser.py` |
| 3.2 | 实现 `PlatformScorer`（评分引擎桩实现） | 3.1 | `core/scoring.py` |
| 3.3 | 实现 `ComparisonReportGenerator`（横向对比报告生成） | 3.1 | `core/comparison_reporter.py` |
| 3.4 | 在 `TestRunner` 中集成评分更新（深度测试完成后自动计算） | 2.6, 3.2 | `web/test_runner.py` (MODIFY) |
| 3.5 | 在 `TestRunner` 中集成对比报告生成 | 2.6, 3.3 | `web/test_runner.py` (MODIFY) |
| 3.6 | 在 `/api/platforms` 响应中包含评分和 Top 模型数据 | 3.2, 2.4 | `web/routes/platforms.py` (MODIFY) |
| 3.7 | 编写评分 + 解析器的单元测试 | 3.1, 3.2 | `tests/test_scoring.py` |

**Phase 3 完成标准**：
- `GET /api/platforms` 返回带评分和 Top 5 模型的列表
- 横向对比测试完成后能生成对比报告
- 报告解析器能正确提取现有报告的关键指标

---

### Phase 4：前端 UI（React + Vite）

**目标**：实现完整的 Web UI 界面。

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 4.1 | 初始化 React + Vite 项目，配置 proxy | — | `frontend/` 目录 |
| 4.2 | 实现全局 CSS 设计系统（暗色主题 + 变量 + 动画） | — | `frontend/src/styles/index.css` |
| 4.3 | 实现 `api/client.js`（统一 fetch + SSE 管理） | — | `frontend/src/api/client.js` |
| 4.4 | 实现基础组件：`Layout`, `ScoreRing`, `StatusIndicator`, `StageProgress` | 4.2 | `frontend/src/components/` |
| 4.5 | 实现 `PlatformCard` 组件（评分环 + 可用率 + Top 模型 + 操作按钮） | 4.4 | `frontend/src/components/PlatformCard.jsx` |
| 4.6 | 实现 `PlatformModal` 组件（新增/编辑弹窗 + 表单验证） | 4.4 | `frontend/src/components/PlatformModal.jsx` |
| 4.7 | 实现 `CompareBar` 组件（浮动底栏） | 4.4 | `frontend/src/components/CompareBar.jsx` |
| 4.8 | 实现 `ReportViewer` 组件（Markdown 报告美化渲染） | 4.4 | `frontend/src/components/ReportViewer.jsx` |
| 4.9 | 实现 `ReportHistory` 组件（历史报告表格 + 下载/删除） | 4.4 | `frontend/src/components/ReportHistory.jsx` |
| 4.10 | 实现 `HomePage`（平台卡片网格 + CRUD + 对比模式 + 排序） | 4.5-4.7, 4.3 | `frontend/src/pages/HomePage.jsx` |
| 4.11 | 实现 `PlatformPage`（详情 + 报告 + 测试 + 状态） | 4.4, 4.8, 4.9, 4.3 | `frontend/src/pages/PlatformPage.jsx` |
| 4.12 | 实现 React Router + App.jsx 路由配置 | 4.10, 4.11 | `frontend/src/App.jsx` |
| 4.13 | 构建生产包 + FastAPI 静态文件挂载 | 4.12, 2.8 | `web/app.py` (MODIFY) |
| 4.14 | 端到端 UI 验证 | 4.13 | — |

**Phase 4 完成标准**：
- 浏览器访问 `http://localhost:8080` 显示完整 UI
- 平台卡片按评分排序，CRUD 操作正确
- 点击平台名跳转详情页，报告正确渲染
- 测试按钮点击后状态灯和进度条实时更新
- 对比模式可选中多平台并启动对比

---

### Phase 5：多用户认证系统（可延后）

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 5.1 | 扩展 DB Schema（users 表 + 双层密钥字段） | — | `data/db.py` (MODIFY) |
| 5.2 | 实现 `AuthService`（注册/登录/改密码/恢复密钥） | 5.1, 1.1 | `core/auth.py` (NEW) |
| 5.3 | 实现 `SessionKeyCache`（DEK 缓存 + 超时清除） | 5.2 | `core/auth.py` |
| 5.4 | 实现 JWT 中间件 + Auth 路由 | 5.2 | `web/routes/auth.py` (NEW) |
| 5.5 | 改造 PlatformManager 支持 per-user 文件 | 5.2, 1.1 | `core/platform_manager.py` (MODIFY) |
| 5.6 | 前端实现登录/注册页面 + AuthContext + ProtectedRoute | 5.4 | `frontend/src/pages/LoginPage.jsx` |
| 5.7 | 前端 API 客户端加入 JWT Token 管理 | 5.6 | `frontend/src/api/client.js` (MODIFY) |
| 5.8 | 集成测试（多用户数据隔离验证） | 5.1-5.7 | `tests/test_auth.py` |

---

### Phase 6：集成验证与优化

| # | 任务 | 依赖 | 产出文件 |
|:---:|:---|:---:|:---|
| 6.1 | 端到端功能验证（所有用户故事路径） | Phase 1-4 | — |
| 6.2 | CLI 完全回归测试 | Phase 1 | — |
| 6.3 | UI 响应式布局验证（桌面/平板/手机） | Phase 4 | — |
| 6.4 | 性能优化（报告渲染、大量平台加载） | Phase 4 | — |
| 6.5 | 更新 requirements.txt + README | Phase 2, 4 | `requirements.txt` (MODIFY) |

---

## 七、文件影响矩阵

### 新增文件（按 Phase 排列）

| Phase | 文件 | 说明 |
|:---:|:---|:---|
| 1 | `core/platform_manager.py` | 统一加密平台注册表管理器 |
| 1 | `core/probe_runner.py` | 提取的可复用探测函数 |
| 1 | `tools/migrate_to_registry.py` | 一次性迁移脚本 |
| 1 | `config/platforms.enc` | 统一加密平台注册表（迁移产出） |
| 1 | `tests/test_platform_manager.py` | PlatformManager 单元测试 |
| 2 | `web/__init__.py` | Web 包 |
| 2 | `web/app.py` | FastAPI 应用工厂 |
| 2 | `web/schemas.py` | 请求/响应数据模型 |
| 2 | `web/dependencies.py` | FastAPI 依赖注入 |
| 2 | `web/test_runner.py` | 后台测试执行管理器 |
| 2 | `web/routes/__init__.py` | 路由包 |
| 2 | `web/routes/platforms.py` | 平台 CRUD API |
| 2 | `web/routes/tests.py` | 测试执行 + SSE |
| 2 | `web/routes/reports.py` | 报告管理 |
| 2 | `run_web.py` | Web 入口脚本 |
| 2 | `tests/test_web_api.py` | API 集成测试 |
| 3 | `core/scoring.py` | 评分引擎 |
| 3 | `core/report_parser.py` | 报告解析器 |
| 3 | `core/comparison_reporter.py` | 横向对比报告生成 |
| 3 | `tests/test_scoring.py` | 评分测试 |
| 4 | `frontend/` | 完整 React + Vite 前端项目 |
| 5 | `core/auth.py` | 认证服务 + Session 缓存 |
| 5 | `web/routes/auth.py` | Auth 路由 |

### 修改文件

| Phase | 文件 | 改动内容 |
|:---:|:---|:---|
| 1 | `core/config.py` | 平台列表改从 PlatformManager 获取 |
| 1 | `run.py` | 使用 PlatformManager，提取 worker |
| 1 | `config/user_config.yaml` | 移除 platforms 节 |
| 2 | `requirements.txt` | 确认 fastapi/uvicorn 版本 |
| 3 | `web/routes/platforms.py` | 加入评分数据 |
| 3 | `web/test_runner.py` | 集成评分和对比 |
| 5 | `data/db.py` | 新增 users 表 |
| 5 | `core/platform_manager.py` | 支持 per-user 文件 |

---

## 八、验证计划

### 8.1 自动化测试

```bash
# Phase 1 回归
pytest api_probe_system/tests/ -v                              # 96 个现有测试
pytest api_probe_system/tests/test_platform_manager.py -v      # 新增 PM 测试

# Phase 2 API 测试
pytest api_probe_system/tests/test_web_api.py -v               # FastAPI TestClient

# Phase 3 评分测试
pytest api_probe_system/tests/test_scoring.py -v

# Phase 1 CLI 端到端
python -m api_probe_system.run --platforms BlazeAI --mode standard

# Phase 1 迁移验证（dry-run）
python -m api_probe_system.tools.migrate_to_registry --dry-run
```

### 8.2 手动验证清单

| 阶段 | 验证项 | 预期结果 |
|:---|:---|:---|
| Phase 1 | `python run.py --all` 正常运行 | 与合并前行为一致 |
| Phase 2 | curl 访问所有 API 端点 | 正确返回 JSON |
| Phase 2 | SSE 连接测试 | 收到阶段事件流 |
| Phase 4 | 浏览器访问主页 | 卡片网格正确渲染 |
| Phase 4 | 新增/编辑/删除平台 | CRUD 操作正确 |
| Phase 4 | 点击平台名跳转详情页 | 报告正确显示 |
| Phase 4 | 启动基本/深度测试 | 状态灯 + 进度条更新 |
| Phase 4 | 横向对比 | 并行测试 + 对比报告生成 |
| Phase 4 | 历史报告下载/删除 | 文件操作正确 |
| Phase 5 | 用户注册 + 登录 | JWT 签发 + 数据隔离 |
| Phase 5 | 修改密码 | 数据不丢失 |
| Phase 5 | 恢复密钥找回 | 数据完整恢复 |

---

*文档结束*
