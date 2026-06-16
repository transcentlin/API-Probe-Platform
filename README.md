# API 平台测试系统 (API Probe Platform)

[![GitHub Stars](https://img.shields.io/github/stars/transcentlin/API-Probe-Platform?style=social)](https://github.com/transcentlin/API-Probe-Platform/stargazers)
[![GitHub Release](https://img.shields.io/github/v/release/transcentlin/API-Probe-Platform?include_prereleases&style=flat-square)](https://github.com/transcentlin/API-Probe-Platform/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-Vite-61DAFB?style=flat-square&logo=react&logoColor=white)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

> **先进的大模型 API 多服务商性能与兼容性评估平台** | An advanced, multi-provider LLM API performance benchmark and evaluation platform.

一个面向 LLM API 服务商的全方位性能、能力及兼容性评估与测试平台。系统提供了统一的 CLI 命令行入口以及直观的 Web 可视化仪表盘，旨在全方位评估并对比各大主流大模型（LLM）API 提供商在核心能力维度上的表现。

---

## 🌟 核心功能

- **多维度能力评估探针 (Probes)**：针对 LLM 核心能力进行深度测评：
  - **Reasoning**：推理与长链思考能力
  - **Tool Calling**：工具/函数调用准确率与参数解析
  - **JSON Mode**：输出结构化 JSON 数据的遵从度
  - **Streaming**：流式传输的响应首包延迟与稳定性
  - **Vision**：多模态/视觉理解评估
  - **Basic Chat & Web Search**：基础对话响应延迟及联网搜索评估
- **无泄漏的零配置安全管理**：采用高强度的本地配置文件加密机制（如 `platforms.enc`），配合系统环境变量注入，从源头上彻底规避 API 密钥和敏感凭证在 Git 提交历史中泄露的风险。
- **统一的双入口操作**：支持便捷的一键 CLI 自动化评估运行，并提供基于 React + Vite 的精美 Web 监控控制台，实时查看测试进度与对比结果。
- **详尽的报告生成与解析**：自动将测试原始日志解析为结构化的评分卡与可视化对比报告。

---

## 🛠️ 技术栈

| 层级 | 技术 |
|---|---|
| **后端/核心引擎** | Python 3.x · FastAPI · HTTPX · PyYAML · Cryptography |
| **前端控制台** | React (Vite) · Vanilla CSS · 现代深色主题 · 微交互动效 |
| **存储** | 轻量级本地文件数据库 · 结构化 JSON 存储 |

---

## 🚀 快速开始

### 准备条件

- Python 3.8+
- Node.js 18+ (用于 Web 前端运行)

### 安装步骤

1. **克隆项目仓库**：
   ```bash
   git clone https://github.com/transcentlin/API-Probe-Platform.git
   cd API-Probe-Platform
   ```

2. **配置后端环境**：
   ```bash
   pip install -r api_probe_system/requirements.txt
   ```

3. **配置前端环境**：
   ```bash
   cd api_probe_system/frontend
   npm install
   ```

### 启动运行

本系统支持 CLI 和 Web 双重入口：

#### 1. 启动 Web 可视化平台（推荐）
启动 FastAPI 后端服务：
```bash
python run_web.py
```
启动 React 前端服务：
```bash
cd api_probe_system/frontend
npm run dev
```

#### 2. CLI 命令行评估模式
您也可以直接在终端针对特定模型或能力运行单个探针：
```bash
python api_probe_system/run.py --help
```

---

## 🔒 凭证配置与安全规范

为了保护您的 API 密钥安全，系统在初始化配置时遵循以下规范：
1. 本地生成纯净的 `platforms.enc` 加密配置载体。
2. 通过环境变量注入各平台的 API Token。
3. 相关的解密 Key 必须置于代码库之外，禁止以任何形式上传至 Git。

---

## 🤝 贡献与反馈

欢迎提出 [Issue](https://github.com/transcentlin/API-Probe-Platform/issues) 或 [Pull Request](https://github.com/transcentlin/API-Probe-Platform/pulls)，共同改进本项目。

如果您觉得本项目对您有帮助，请给我们一个 ⭐ Star，这是对开源开发者最大的鼓励！

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
