# Ollama 云端模型拉取与部署操作指南

本指南旨在指导您如何将所需的 AI 模型拉取并部署到您的 **Ollama Cloud（云空间）**中。

在部署成功后，本系统的探测引擎（Stage 2.5 & Stage 3）即可顺利通过可用性预检，对您的云端模型进行全面的能力与边界探测，而不再返回 `HTTP 404` 错误。

---

## 1. 核心原理：为什么会返回 404？

Ollama Cloud 遵循**“按需拉取（On-Demand Pulling）”**的云原生机制：
* 您的云端 API 默认处于空状态。虽然 API 能列出您账户关注或预设的全部模型 tags（Stage 2 成功获取 42 个模型），但在未手动“拉取（Pull）”或运行（Run）前，云服务并没有为该模型分配和启动对应的推理计算资源。
* 此时直接请求该模型的 `/api/chat`，官方网关会判定资源不存在并返回 `HTTP 404`。
* **解决方案**：在您的个人云端环境中，将需要测试的模型 `pull` 下来并使之处于 `online` 状态。

---

## 2. 操作前提

1. **拥有官方账号**：在 [ollama.com](https://ollama.com) 注册并登录。
2. **生成云端密钥**：在 [ollama.com/settings/keys](https://ollama.com/settings/keys) 生成您的 API Key，确保已填入本探测系统的加密配置中。
3. **本地安装 Ollama CLI**：本地电脑需要安装有 Ollama 客户端命令行工具。

---

## 3. 操作步骤

### 第一步：在本地终端登录并绑定云空间

在您的本地终端（PowerShell 或 Bash）中，执行登录命令以将本地 CLI 客户端与官方云空间绑定：

```bash
ollama signin
```

*系统会提示您在浏览器中完成登录授权，或者生成一组设备绑定代码，按照屏幕提示操作即可。*

---

### 第二步：拉取目标模型到云端空间

使用 `ollama pull` 命令并指定云端标记，将大模型拉取到您的云空间实例中：

```bash
# 格式：ollama pull <model_name>:<tag> --cloud
# 示例：拉取 Llama 3.2 3B 基础模型到您的云空间
ollama pull llama3.2:3b --cloud
```

> [!TIP]
> **关于套餐限额**：
> * **免费版（Free Tier）**：通常有单模型尺寸限制（例如仅支持拉取 8B 以下的小模型）和并发运行实例数限制。建议优先拉取 `llama3.2:3b` 或 `qwen2.5:7b` 进行测试。
> * **专业版/最高版（Pro/Max Tier）**：能拉取更大的模型（如 70B 或 405B）并在云端保持常驻。

---

### 第三步：验证云端部署状态

拉取完成后，您可以通过以下命令查看您的云端空间内当前已成功就绪并在线的模型列表：

```bash
ollama list --cloud
```

若目标模型显示在列表中且状态正常（`online` 或 `ready`），代表其在云端已可随时接受 API 推理请求。

---

### 第四步：手动测试接口连通性（可选）

在运行探测系统前，您可以通过 `curl` 指令手动在终端快速向云端发送测试包，验证 404 是否已消除：

```bash
curl -X POST https://ollama.com/api/chat \
  -H "Authorization: Bearer <您的_OLLAMA_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:3b",
    "messages": [
      {"role": "user", "content": "Hi"}
    ],
    "stream": false
  }'
```

**预期结果**：返回正常的 JSON 对话内容（包含 `"message": {"role": "assistant", "content": "..."}`），说明模型已成功拉起，预检通道畅通。

---

## 4. 重新运行探测

当您在云端部署好对应的模型后，启动探测系统：

```bash
python api_probe_system/run.py --platforms Ollama --mode standard
```

**此时引擎的执行流变化**：
1. **Stage 2** 发现 42 个模型。
2. **Stage 2.5 (预检)** 嗅探您刚拉取的模型（如 `llama3.2:3b`）。由于它在云端处于在线状态，预检会拿到 `HTTP 200` 并判定其为 **可用模型**。
3. **Stage 3 - 5** 会成功被调度，开始对此可用模型进行 8 项能力（工具调用、流式等）及边界 RPM 的真实黑盒测试，并产出拥有详尽能力矩阵的 Ollama 探测报告！
