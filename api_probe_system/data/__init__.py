"""数据访问层（Data Layer）—— 封装存储细节，上层通过 Repository 接口访问。

子模块：
    db            SQLite 连接与建表（schema 初始化）
    repositories  Repository 接口与 SQLite 实现
    profile_store ProfileStore 画像 YAML 写入
"""
