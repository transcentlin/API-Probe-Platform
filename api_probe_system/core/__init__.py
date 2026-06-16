"""业务逻辑层（Core Engine）—— 系统心脏，零 UI 依赖。

子模块：
    constants  常量与异常定义
    models     核心数据模型（ProbeContext、各 StageResult 等）
    secret     SecretResolver 密钥解析与脱敏
    config     ConfigManager 配置管理 + ConfigStore
    adapters   FormatAdapter 格式适配器插件
    engine     ProbeEngine 探测引擎 + Stage0~5
    probes     CapabilityProbe 能力探针插件（M2 引入）
"""
