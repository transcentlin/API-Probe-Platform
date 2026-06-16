# 独立项目设计方案：ConfigCrypt — 通用敏感信息管理工具

## Context

当前 `api_probe_system` 已实现 `core/vault.py` + `tools/manage_keys.py`：用 Fernet+PBKDF2
加密 `.env.enc`、主密码存 OS Keychain。功能已能服务于探测系统自身，但 **业界没有现成
工具完整覆盖「明文⇄密文双向 + Keychain + Python 原生 + GUI」这一组合需求**——dotenvx
缺 Keychain、SOPS 缺 GUI、senv 单功能。

本方案把现有 vault 能力剥离成独立项目 **ConfigCrypt**，按"用户视角最方便高效"原则设计
CLI + GUI 双形态，作为今后所有涉及敏感信息项目的通用底座。

**目标读者**：实施这个项目的下一个 LLM/开发者。这份文档应自包含、可直接执行。

---

## 一、产品定位

| 项 | 内容 |
|---|---|
| 产品名 | ConfigCrypt |
| 一句话定位 | 单机用户的本地密钥保险箱：加密文件 + OS Keychain 主密码 + CLI 与 GUI 双形态 |
| 目标用户 | 个人开发者（管理多项目 API Key）、小团队（共享加密文件，各自存主密码） |
| 不目标用户 | 团队级密钥分发（用 HashiCorp Vault）、CI/CD 自动注入（用 SOPS） |
| 核心差异化 | OS Keychain 集成 + 同时给 CLI 与 GUI 两套自然体验 |
| 许可证 | MIT |

---

## 二、用户场景与体验目标

### 场景 1 — 首次使用（新设备）

**用户视角**：装完 ConfigCrypt 后，**90 秒内**完成首份保险箱建立。

GUI 路径：双击启动 → 引导界面「欢迎使用 ConfigCrypt」→ 设主密码（强度提示）→ 选「逐条录入」或「从 .env 文件导入」→ 完成。
CLI 路径：`kv init` → 同样引导式问答。

### 场景 2 — 日常查看（已知键名找值）

**GUI**：启动后窗口列出所有键名（默认脱敏），点条目右侧 👁 显示 5 秒后自动隐藏；点 📋 复制到剪贴板（30 秒后自动清空）。
**CLI**：`kv show GITHUB_TOKEN`（脱敏）或 `kv show GITHUB_TOKEN --reveal`。

### 场景 3 — 批量录入（密码管理器导出后导入）

**GUI**：拖拽 .env 文件到窗口 → 弹"将合并 5 个键，其中 2 个会覆盖已有项" → 点确认。
**CLI**：`kv import keys.env --merge`。

### 场景 4 — 修改/增删（高频）

**GUI**：点条目编辑铅笔 → 弹改键值对话框 → 保存；右键删除。或顶栏「全部编辑」→ 弹文本编辑器风格区域。
**CLI**：`kv add NEW_KEY` / `kv remove OLD_KEY` / `kv edit`（调 $EDITOR）。

### 场景 5 — 跨设备迁移

**用户视角**：保险箱密文可放 git/网盘/U 盘。新设备装 ConfigCrypt → 把 `.kv.enc` 拷过去 → 启动 GUI → 提示输主密码 → 自动写入新设备 Keychain → 完成。

### 场景 6 — 给其他项目用（库模式）

```python
# 第三方项目代码示例
from ConfigCrypt import Vault
vault = Vault.open()                # 自动从 Keychain 取主密码解锁
api_key = vault["BlazeAI_API_KEY"]  # 取明文
```

### 场景 7 — 紧急情况

**忘记主密码**：GUI 与 CLI 都明确提示「无后门」+ 给出"删除文件重新 init"的选项（带二次确认）。
**Keychain 主密码错**：GUI 弹密码输入对话框（最多 3 次）；CLI 走 getpass 同样 3 次重试。

### UX 设计原则

1. **最小输入** — 解锁后所有操作不再问主密码（缓存进程内存）
2. **可逆撤销** — 删除前二次确认；明文显示后自动隐藏
3. **零隐式状态** — 当前保险箱路径、解锁状态、未保存改动始终在 GUI 顶栏可见
4. **键盘优先** — GUI 全功能可键盘操作（Ctrl+N 新键、Ctrl+F 搜索、Esc 隐藏明文）
5. **跨平台一致** — Windows / macOS / Linux 行为一致，特别是 Keychain 后端的差异由库屏蔽

---

## 三、技术架构

```
┌────────────────────────────────────────────────────────┐
│           UI 层（独立运行入口）                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐   │
│  │  CLI (kv)   │  │  GUI (kv-ui)│  │   Library     │   │
│  │  click     │  │  PySide6    │  │   from kv ... │   │
│  └─────┬──────┘  └─────┬───────┘  └──────┬────────┘   │
└────────┼─────────────────┼─────────────────┼───────────┘
         │                 │                 │
         └─────────────────┴─────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────┐
│           Service 层（业务规则、与 UI 无关）             │
│   VaultService                                          │
│     - unlock(master_pw) / lock()                        │
│     - add / get / list / remove / rename                │
│     - import_from_env / export_to_env                   │
│     - edit_via_external_editor                          │
│     - change_master_password / rotate                   │
│     - is_unlocked / is_dirty                            │
└─────────────────────────┬──────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────┐
│           Core 层（加解密原语）                          │
│   Vault         — Fernet+PBKDF2，加密文件 IO            │
│   KeychainStore — keyring 封装，跨平台屏蔽差异          │
│   EnvParser     — .env 格式读写（KEY=value、注释、空行） │
│   ClipboardGuard— 复制到剪贴板，N 秒后自动清空            │
└────────────────────────────────────────────────────────┘
```

**分层目的**：UI 层（CLI / GUI / Library）共用同一个 `VaultService`，业务规则不重复实现。
新增 UI 形态（如未来加 Web UI、TUI）只需新建 UI 层模块。

---

## 四、关键技术选型

| 关切 | 选型 | 理由 |
|---|---|---|
| 加密 | `cryptography.Fernet` + `PBKDF2HMAC-SHA256`（200k 轮） | 已在原项目验证；Fernet 内置 HMAC，篡改即报错 |
| OS Keychain | `keyring` 库 | Windows Credential Manager / macOS Keychain / Linux Secret Service 统一封装 |
| 文件格式 | 加密前是 JSON（`dict[str, str]`），加密后是 Fernet 二进制 | JSON 易调试、Fernet 自带版本前缀方便未来升级 |
| CLI 框架 | **click**（不要用 argparse） | 子命令、选项分组、彩色输出更顺手；社区标准 |
| GUI 框架 | **PySide6**（LGPL 可商用） | 跨平台、原生外观、长期可维护；CustomTkinter 备选 |
| 配置目录 | 跨平台 platformdirs：Win=`%APPDATA%/ConfigCrypt`、macOS=`~/Library/Application Support/ConfigCrypt`、Linux=`~/.config/ConfigCrypt` | 默认保险箱路径 `<config_dir>/default.kv.enc` |
| 包管理 | `pyproject.toml` + `hatchling` | 现代 Python 标准 |
| 测试 | `pytest` + `pytest-asyncio` + `pytest-qt`（GUI） | 与原项目一致 |
| CI | GitHub Actions：三平台跑测试 + 构建独立可执行（PyInstaller） |
| 发布 | PyPI（库 + CLI） + GitHub Releases（GUI 独立二进制） |

---

## 五、CLI 设计

### 命令一览（10 个）

| 命令 | 作用 | 关键选项 |
|---|---|---|
| `kv init` | 引导式建保险箱 | `--from-env <PATH>` 从已有 .env 导入 |
| `kv unlock` | 显式解锁并写 Keychain（首次跨设备用） | — |
| `kv lock` | 从 Keychain 删主密码 | — |
| `kv status` | 显示保险箱路径、键数、是否解锁、Keychain 命中情况 | — |
| `kv list` | 列出所有键（默认脱敏） | `--reveal` 明文、`--format json` |
| `kv show <KEY>` | 单键脱敏 | `--reveal`、`--copy`（复制到剪贴板，30s 自清） |
| `kv add <KEY>` | 新增/覆盖（getpass 输值） | `--value <V>`（脚本用，警告不安全） |
| `kv remove <KEY>` | 删除（二次确认） | `--yes` 跳过确认 |
| `kv rename <OLD> <NEW>` | 改键名 | — |
| `kv encrypt <FILE>` | 明文 .env → 加密文件 | `--keep`（默认删源）、`--out PATH` |
| `kv decrypt` | 加密文件 → 明文 .env | `--to PATH`、`--force` 覆盖、自动 chmod 600 |
| `kv edit` | 解密到临时文件 → $EDITOR → 保存后重加密 | `--editor <CMD>` |
| `kv import <FILE>` | 增量导入 .env 到现有保险箱 | `--merge`、`--replace`、`--prefix <X>` |
| `kv export` | 导出整个保险箱为 .env | `--to PATH`、`--force` |
| `kv reveal-all` | 一次性打印全部明文（二次确认） | — |
| `kv reset-password` | 改主密码 | — |
| `kv rotate` | 重新加密（轮换 PBKDF2 盐 + 改主密码） | — |

### 全局选项

- `--vault <PATH>` 指定保险箱文件（覆盖默认路径）
- `--profile <NAME>` 多保险箱切换（如个人 / 工作）
- `--quiet` 静默
- `--json` 结构化输出（脚本友好）

### CLI 体验示例

```bash
$ kv init --from-env ~/.env.legacy
[ConfigCrypt] 欢迎首次使用！
请设置主密码（不会显示，至少 8 位）：
再输入一次确认：
[OK] 已从 ~/.env.legacy 导入 12 个键。
[OK] 保险箱已创建：~/.config/ConfigCrypt/default.kv.enc
[OK] 主密码已存入 OS Keychain。
[提示] 已安全删除源文件 ~/.env.legacy。

$ kv list
GITHUB_TOKEN          ghp_...xxxx
BlazeAI_API_KEY       blz_...xECw
OPENAI_API_KEY        sk-p...4def
... 共 12 项

$ kv show GITHUB_TOKEN --copy
[OK] 已复制 GITHUB_TOKEN 到剪贴板，30 秒后自动清空。

$ kv edit
[OK] 已解密到临时文件 /tmp/kv-edit-xxx.env（仅当前用户可读）
启动编辑器 vim ...
（保存退出后）
[OK] 已重新加密。变更：+2 新增、-1 删除、~3 修改。
[OK] 临时文件已安全清除。
```

---

## 六、GUI 设计

### 整体结构

**单窗口**应用，分三大区域：

```
┌────────────────────────────────────────────────────────────┐
│  🔒 ConfigCrypt         default.kv.enc ▾    [🔓 已解锁  退出]  │  ← 顶栏
├──────────────────────┬─────────────────────────────────────┤
│                      │                                      │
│  🔍 搜索...          │  键名：GITHUB_TOKEN                  │
│                      │                                      │
│  ┌──────────────────┐│  值：  ghp_…xxxx     [👁][📋]       │
│  │ BlazeAI_API_KEY  ││                                      │
│  │ GITHUB_TOKEN  ●  ││  备注：（可选自由文本，多行）         │
│  │ OPENAI_API_KEY   ││  ┌─────────────────────────┐         │
│  │ GROQ_API_KEY     ││  │ 我的个人 PAT，作用域：      │         │
│  │ ...              ││  │ repo, workflow            │         │
│  └──────────────────┘│  └─────────────────────────┘         │
│                      │                                      │
│  [+ 新增]  [删除]    │  最后修改：2026-06-04 21:53          │
│                      │                                      │
├──────────────────────┴─────────────────────────────────────┤
│  共 12 项 │ ✏ 未保存改动: 2 │ 自动保存关闭                  │  ← 状态栏
└────────────────────────────────────────────────────────────┘
```

### 详细组件

#### 顶栏
- 应用标题与图标
- **保险箱切换下拉**：列出已知保险箱（多 profile），点 + 可加新文件
- **解锁状态**：🔓 已解锁 / 🔐 已锁定。锁定状态下右侧主区域被遮罩
- **菜单**：文件（新建/打开/导出/导入/退出）、编辑（增/删/复制/搜索）、视图（明暗主题切换）、工具（主密码改、轮换、外部编辑器编辑、查看 Keychain 状态）、帮助

#### 左侧列表
- 搜索框（实时过滤）
- 键列表（脱敏显示，名字 + 短脱敏值）
- 选中时右侧主区域同步
- 列表项右键菜单：复制值（含 30 秒倒计时提示）、显示明文、编辑、删除、改名
- 底部 `[+ 新增]` `[删除]` 按钮（与右键等价）

#### 右侧详情
- 键名（只读，点 ✏ 进入改名）
- 值字段：默认脱敏；点 👁 临时显示 5 秒；点 📋 复制并清空
- 备注字段：多行编辑（可选 —— 给敏感数据加上下文，类似 1Password 的 notes）
- 最后修改时间戳
- 底部"应用"/"撤销"按钮（如果详情区有未保存改动）

#### 弹窗与对话框
- **首次启动**：欢迎引导（设主密码 → 选导入或空白）
- **解锁**：输入主密码（含"显示密码"切换、3 次错误提示 reset）
- **新增/编辑**：键名 + 值（getpass 风格隐藏） + 备注
- **导入 .env**：拖拽或浏览文件 → 显示 diff 预览（哪些新增/哪些覆盖） → 确认
- **导出**：警告对话框 → 选目标路径 → 完成后提示"导出文件含明文，请妥善保管"
- **改主密码**：当前密码 + 新密码 + 确认 + 强度提示
- **强制重置**：「我忘记主密码了」按钮 → 严正警告 → 二次确认 → 删除文件 → 引导重建

#### 自动安全行为
- **空闲自动锁**：5 分钟无操作自动锁定（可配置 1-60 分钟、可关闭）
- **窗口最小化自动隐藏明文**：所有 👁 显示状态恢复脱敏
- **关闭即清剪贴板**：退出时清空所有 ConfigCrypt 写入的剪贴板内容
- **系统休眠/锁屏自动锁**：监听 OS 信号

#### 主题
- 跟随系统明暗（macOS/Win11）
- 内置「专注模式」：极简紧凑布局，无边框

### 键盘快捷键

| 快捷键 | 作用 |
|---|---|
| Ctrl/Cmd+N | 新增键 |
| Ctrl/Cmd+F | 焦点到搜索框 |
| Ctrl/Cmd+C | 复制选中键的值（自动 30 秒清空） |
| Ctrl/Cmd+E | 编辑选中键 |
| Delete | 删除选中键 |
| Ctrl/Cmd+L | 立即锁定 |
| Esc | 隐藏所有明文 / 关闭对话框 |
| Ctrl/Cmd+, | 设置 |

---

## 七、Library API 设计

```python
from ConfigCrypt import Vault, VaultError, KeyNotFound

# 默认路径 + 自动从 Keychain 取主密码
vault = Vault.open()

# 自定义路径
vault = Vault.open(path="~/work/.kv.enc")

# 主密码显式传入（脚本/CI 场景）
vault = Vault.open(master_password="...")

# 字典风格读写
api_key = vault["GITHUB_TOKEN"]     # 取明文
vault["NEW_KEY"] = "value"           # 加密保存
del vault["OLD_KEY"]
"GITHUB_TOKEN" in vault              # True

# 批量
vault.update({"K1": "v1", "K2": "v2"})
vault.import_env("/path/to/.env", strategy="merge")
vault.export_env("/path/to/out.env")  # 警告级 API

# 上下文管理（自动锁）
with Vault.open() as v:
    use(v["KEY"])
# 退出块自动清内存
```

**API 设计原则**：尽量像 dict，降低集成成本。

---

## 八、文件结构（独立项目）

```
ConfigCrypt/
├── pyproject.toml
├── README.md
├── LICENSE                       # MIT
├── CHANGELOG.md
├── src/
│   └── ConfigCrypt/
│       ├── __init__.py           # 导出 Vault / VaultError 等
│       ├── core/
│       │   ├── vault.py          # Vault 类（核心加解密 + 文件 IO）
│       │   ├── keychain.py       # KeychainStore（keyring 封装）
│       │   ├── env_parser.py     # .env 格式读写
│       │   ├── clipboard.py      # ClipboardGuard
│       │   └── exceptions.py     # 异常体系
│       ├── service/
│       │   └── vault_service.py  # VaultService（业务编排，UI 共用）
│       ├── cli/
│       │   ├── __main__.py       # 入口 `python -m ConfigCrypt`
│       │   ├── main.py           # click 主组
│       │   └── commands/         # 每个子命令一文件
│       ├── gui/
│       │   ├── __main__.py       # 入口 `python -m ConfigCrypt.gui`
│       │   ├── app.py            # QApplication 与主窗口
│       │   ├── main_window.py
│       │   ├── dialogs/          # 各类对话框
│       │   ├── widgets/          # 自定义组件（脱敏标签等）
│       │   ├── theme.py
│       │   └── resources/        # 图标、qss
│       └── utils/
│           └── platformdirs_helper.py
├── tests/
│   ├── unit/
│   │   ├── test_vault.py
│   │   ├── test_keychain.py
│   │   ├── test_env_parser.py
│   │   ├── test_clipboard.py
│   │   └── test_vault_service.py
│   ├── cli/
│   │   └── test_commands.py      # 用 click.testing.CliRunner
│   └── gui/
│       └── test_main_window.py   # 用 pytest-qt
├── docs/
│   ├── index.md
│   ├── cli.md
│   ├── gui.md
│   ├── library.md
│   ├── security.md               # 安全模型、威胁分析
│   └── adr/                      # 架构决策记录
└── .github/
    └── workflows/
        ├── test.yml              # 三平台 CI
        └── release.yml           # PyInstaller 构建 + PyPI 发布
```

**入口脚本**（pyproject.toml）：
```toml
[project.scripts]
kv = "ConfigCrypt.cli.main:cli"
kv-ui = "ConfigCrypt.gui.app:main"
```

---

## 九、安全模型

### 威胁与对策

| 威胁 | 对策 |
|---|---|
| .env.enc 被复制走 | 文件无主密码无法解密；主密码强度由 PBKDF2 200k 轮 + 用户密码长度共同保障 |
| 内存里明文被 dump | 解锁后明文仅在 service 层 dict 中；GUI 显示后 5 秒清；剪贴板 30 秒清；空闲 5 分钟自动锁 |
| Keychain 主密码被读 | 这等于设备已沦陷；Keychain 是 OS 信任根，ConfigCrypt 不再加额外防护 |
| 键盘记录 | 文档警告：高敏感环境不建议在已感染机器使用 |
| 编辑器残留（编辑明文 .env） | 临时文件用 `tempfile.NamedTemporaryFile(mode='w', delete=False)`，路径在 `/tmp` 或 `%TEMP%`；退出时 zero-fill 覆盖后删除（best effort，文档说明 SSD 上无完美保证） |
| 误删保险箱 | 首次启动后默认开启自动备份：在同目录建 `.kv.enc.bak`，每次写入前轮换；保留最近 5 份 |
| Side-channel | PBKDF2 / Fernet 由 `cryptography` 库提供，已是工业级 |

### 不在范围内的威胁

- 团队级密钥共享（设计假设单用户）
- 操作系统级 root 攻击者
- 物理 RAM 读取

明文写在 `docs/security.md`，让用户清楚边界。

---

## 十、与 `api_probe_system` 的集成

完成 ConfigCrypt 项目后，原项目的迁移路径：

1. `pip install ConfigCrypt`
2. 删除 `api_probe_system/core/vault.py`、`tools/manage_keys.py`、`tests/test_vault.py`
3. `core/secret.py` 改为：
   ```python
   from ConfigCrypt import Vault
   _vault: Vault | None = None
   def load_vault():
       global _vault
       _vault = Vault.open()  # 自动 Keychain
   def resolve(api_key: str) -> str:
       if api_key.startswith("${") and api_key.endswith("}"):
           name = api_key[2:-1]
           if _vault and name in _vault:
               return _vault[name]
           ...  # 环境变量回退
   ```
4. `run.py` 的 `unlock_vault()` 改用 `ConfigCrypt.Vault.open()`
5. 跑现有 86 个单测确保通过

迁移工作量：约 50 行 diff。

---

## 十一、交付里程碑

| 里程碑 | 内容 | 验证标准 |
|---|---|---|
| M1 Core 层 | Vault / KeychainStore / EnvParser / ClipboardGuard + 单测 | 覆盖率 ≥90%，三平台 CI 全绿 |
| M2 Service 层 | VaultService 完整业务编排 + 单测 | 所有场景在 service 层可纯函数测试 |
| M3 CLI | 16 个子命令 + click.testing 测试 + `--json` | 用户能完成场景 1-7 全部操作 |
| M4 GUI 框架 | 主窗口 + 解锁/锁定 + 列表 + 详情 + 增删改 | 可视化跑通场景 1-5 |
| M5 GUI 高级 | 拖拽导入、明暗主题、空闲锁、自动备份、剪贴板自清 | 用户体验测试通过 |
| M6 库 | `from ConfigCrypt import Vault` + 上下文管理器 | 接入 `api_probe_system` 通过 |
| M7 打包发布 | PyPI + GitHub Releases（PyInstaller 单文件） | `pip install ConfigCrypt` + 双击 GUI 可用 |
| M8 文档 | README + cli.md + gui.md + library.md + security.md | 新用户能 5 分钟上手 |

---

## 十二、验证方案

### 单元测试

- Core 层覆盖 90%+：加解密回环、错误主密码、篡改密文、空 dict、大 dict、Unicode、Keychain mock
- Service 层覆盖所有业务路径：dirty 标记、锁/解锁、import 三种策略、export 安全护栏
- CLI 用 `click.testing.CliRunner` 跑所有子命令的正/反路径
- GUI 用 `pytest-qt` 跑关键交互：解锁、新增、删除、编辑、搜索过滤、空闲锁

### 端到端冒烟（三平台 CI 自动跑）

1. `kv init` → `kv add K1` → `kv add K2` → `kv list` → `kv lock` → `kv unlock` → `kv show K1 --reveal`
2. 写 .env → `kv encrypt` → 确认源已删 → `kv decrypt --to /tmp/x.env` → diff 一致
3. GUI 启动 → 显示锁定状态 → 输入密码 → 列表渲染 → 点选条目 → 显示明文 → 自动隐藏

### 用户体验测试（人工）

招募 3-5 个开发者按场景 1-7 操作，记录卡点、误操作、需要看文档的瞬间。
"90 秒内完成首份保险箱建立" 作为 KPI。

### 安全测试

- 密文篡改 → 解密拒绝
- Keychain 主密码错 → 提示重输
- 剪贴板 30 秒后真清空（pyclip 验证）
- 临时编辑文件退出后不可读

---

## 十三、给实施者的提示

1. **先做 Core 层并写完测试再动 UI**。Core 稳定后 CLI 和 GUI 只是壳，开发效率会高很多。
2. **CLI 和 GUI 不要直接调 Core，必须通过 Service**。否则业务规则会在两层重复，长期维护噩梦。
3. **PySide6 的入门成本被高估了**。`pythonguis.com` 有非常完整的免费教程，对照写就行。
4. **Keychain 的跨平台差异要专门测试**。Linux 默认后端 `SecretService` 在无桌面环境（如 SSH/容器）下不可用，要给 fallback（文件 + 主密码二次输入）。
5. **打包 GUI 时用 PyInstaller `--onefile`**。Windows 还要签名（防 SmartScreen 警告，可选）。
6. **别加云同步**。这是单机工具，加云同步会让安全模型变复杂。用户可以自己用 Syncthing 或网盘同步加密文件。
7. **不实现"密码生成器"** 这种功能。专注密钥**存储**，不做密码**创造**——避免功能蔓延。
8. **参考 1Password / Bitwarden 的交互细节**，但不要试图复刻它们的全部功能。

---

## 参考来源

调研对比的同类工具：
- [dotenvx/dotenvx](https://github.com/dotenvx/dotenvx) — dotenv 作者出品，业界主流，无 Keychain
- [getsops/sops](https://github.com/getsops/sops) — CNCF 项目，支持 .env，无 Keychain
- [jaydenwindle/senv](https://github.com/jaydenwindle/senv) — 简洁的 .env 加解密，无 Keychain
- [anthonynsimon/secrets-vault](https://github.com/anthonynsimon/secrets-vault) — Python 原生，有 edit，无 Keychain
- [hashicorp/vault](https://github.com/hashicorp/vault) — 重量级团队级方案，不适合

GUI 选型参考：
- [pythonguis.com — Which Python GUI library should you use in 2026?](https://www.pythonguis.com/faq/which-python-gui-library/)
