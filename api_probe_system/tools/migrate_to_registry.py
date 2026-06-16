# -*- coding: utf-8 -*-
"""一键配置迁移工具：将 user_config.yaml (platforms) + .env.enc 合并为 platforms.enc。"""

import argparse
import getpass
import os
import sys
from pathlib import Path
import yaml

# 确保 api_probe_system 路径在 sys.path 中以支持直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api_probe_system.core.vault import EnvVault, VaultDecryptError, VaultError
from api_probe_system.core.platform_manager import PlatformManager, PlatformEntry
from api_probe_system.core.secret import SecretResolver


def resolve_val(val: str, secrets: dict[str, str]) -> str:
    """解析配置值，处理 ${VAR} 格式的变量引用。"""
    if val.startswith("${") and val.endswith("}"):
        var_name = val[2:-1]
        if var_name in secrets:
            return secrets[var_name]
        env_val = os.getenv(var_name)
        if env_val is not None:
            return env_val
        raise ValueError(f"未能在解密的保险箱或环境变量中找到变量: {var_name}")
    return val


def main():
    parser = argparse.ArgumentParser(description="一键迁移双源配置为统一加密平台注册表。")
    parser.add_argument("--master-password", help="主密码（若 Keychain 中没有则需要提供）")
    parser.add_argument("--dry-run", action="store_true", help="干跑模式，仅输出迁移预览而不修改任何文件")
    args = parser.parse_args()

    # 1. 确定路径
    project_root = Path(__file__).resolve().parent.parent
    yaml_path = project_root / "config" / "user_config.yaml"
    env_enc_path = project_root / "config" / ".env.enc"
    registry_path = project_root / "config" / "platforms.enc"

    print("=== 开始配置迁移 ===")
    print(f"配置文件路径: {yaml_path}")
    print(f"密钥保险箱路径: {env_enc_path}")
    print(f"目标注册表路径: {registry_path}")

    if not yaml_path.exists():
        print(f"[错误] user_config.yaml 不存在，迁移终止。")
        sys.exit(1)

    # 2. 加载主密码
    master_password = args.master_password
    if not master_password:
        master_password = EnvVault.load_master_from_keychain()
        if master_password:
            print("已成功从系统 Keychain 自动加载主密码。")
        else:
            print("未能从系统 Keychain 获取主密码，请输入以解锁 .env.enc：")
            master_password = getpass.getpass("主密码: ")

    if not master_password:
        print("[错误] 未提供主密码，迁移终止。")
        sys.exit(1)

    # 3. 解密 .env.enc
    secrets = {}
    if env_enc_path.exists():
        try:
            secrets = EnvVault.decrypt(master_password)
            print(f"成功解密 .env.enc，加载了 {len(secrets)} 个密钥变量。")
        except VaultDecryptError:
            print("[错误] 主密码错误，无法解密 .env.enc。")
            sys.exit(1)
        except Exception as e:
            print(f"[错误] 读取 .env.enc 失败: {e}")
            sys.exit(1)
    else:
        print("[警告] .env.enc 密钥保险箱不存在，仅能解析系统环境变量中的变量。")

    # 4. 加载 user_config.yaml 并解析
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
    except Exception as e:
        print(f"[错误] 解析 user_config.yaml 失败: {e}")
        sys.exit(1)

    platforms_config = config_data.get("platforms", []) if config_data else []
    if not platforms_config:
        print("[警告] user_config.yaml 中没有 platforms 配置。")

    # 5. 构建平台条目
    entries: list[PlatformEntry] = []
    has_errors = False
    for p in platforms_config:
        name = p.get("name")
        base_url_raw = p.get("base_url")
        api_key_raw = p.get("api_key")
        notes = p.get("notes", "")
        website = p.get("website", "")
        hints = p.get("hints", {})

        if not name or not base_url_raw or not api_key_raw:
            print(f"[错误] 平台配置缺失必填字段 (name/base_url/api_key): {p}")
            has_errors = True
            continue

        try:
            base_url = resolve_val(base_url_raw, secrets)
            api_key = resolve_val(api_key_raw, secrets)
            entries.append(PlatformEntry(
                name=name,
                base_url=base_url,
                api_key=api_key,
                enabled=True,
                notes=notes,
                website=website,
                hints=hints
            ))
            masked_key = SecretResolver.mask(api_key)
            print(f"成功解析平台 [{name}]: URL={base_url}, Key={masked_key}")
        except Exception as e:
            print(f"[错误] 解析平台 [{name}] 的变量失败: {e}")
            has_errors = True

    if has_errors:
        print("[错误] 解析平台配置过程中存在错误，迁移终止。")
        sys.exit(1)

    # 5.1 自动扫描并补充未在 user_config.yaml 中注册的隐藏平台
    existing_names = {entry.name.lower() for entry in entries}
    auto_added_count = 0
    for key, val in secrets.items():
        if key.endswith("_API_KEY"):
            prefix = key[:-8]
            base_url_key = prefix + "_BASE_URL"
            if base_url_key in secrets:
                if prefix.lower() not in existing_names:
                    api_key = val
                    base_url = secrets[base_url_key]
                    if not api_key or not base_url:
                        continue
                    entries.append(PlatformEntry(
                        name=prefix,
                        base_url=base_url,
                        api_key=api_key,
                        enabled=True,
                        notes="自动从加密保险箱导入",
                        website="",
                        hints={}
                    ))
                    existing_names.add(prefix.lower())
                    auto_added_count += 1
                    print(f"自动检测并导入隐藏平台 [{prefix}]: URL={base_url}, Key={SecretResolver.mask(api_key)}")

    if auto_added_count > 0:
        print(f"提示: 共自动检测并补充了 {auto_added_count} 个隐藏的 API 平台。")

    print(f"\n解析完成，共得到 {len(entries)} 个平台条目。")

    # 6. 保存或干跑
    if args.dry_run:
        print("\n=== 干跑模式 (Dry-Run) ===")
        print("以下平台将被迁移至加密注册表 platforms.enc:")
        for idx, entry in enumerate(entries, 1):
            print(f"  {idx}. {entry.name} -> URL: {entry.base_url}, Key: {SecretResolver.mask(entry.api_key)}")
        print("user_config.yaml 中的 platforms 节将被移除，仅保留全局 defaults 配置。")
        print("=== 干跑结束 ===")
    else:
        # 执行正式迁移
        try:
            # 写入加密注册表
            pm = PlatformManager(master_password, registry_path=registry_path)
            pm._platforms = entries
            pm._save()
            print(f"[成功] 平台信息已加密写入 {registry_path}")

            # 精简 user_config.yaml，尝试保留 defaults 注释
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_content = f.read()

            if "platforms:" in yaml_content:
                idx = yaml_content.find("platforms:")
                defaults_idx = yaml_content.find("defaults:")
                if defaults_idx < idx and defaults_idx != -1:
                    # 仅保留 platforms 之前的内容
                    new_content = yaml_content[:idx].rstrip() + "\n"
                    with open(yaml_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                else:
                    # 降级方案：使用 safe_dump 写入
                    if "platforms" in config_data:
                        del config_data["platforms"]
                    with open(yaml_path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(config_data, f, allow_unicode=True)
                print(f"[成功] user_config.yaml 已被精简，排除了 platforms 节点。")
            else:
                print("[提示] user_config.yaml 中未找到 platforms 节点，未做修改。")

            print("\n=== 迁移成功完成 ===")
            print("提示：现在可以使用重构后的系统或 CLI 启动了。")
        except Exception as e:
            print(f"[错误] 写入加密配置或修改 user_config.yaml 失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
