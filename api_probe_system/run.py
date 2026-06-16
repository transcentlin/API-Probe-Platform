# 修改历史 (Revision History)
# ==================================
# 版本: v1.2
# 日期: 2026-06-16
# 修改说明: 在 unlock_vault 中增加首次自动初始化引导，当 platforms.enc 缺失时自动加密 platforms_default.json 模板生成新的注册表。
# ----------------------------------
# 版本: v1.1
# 日期: 2026-06-15
# 修改说明: 改造 run.py 引入 PlatformManager 管理平台，并使用外部提取的 probe_runner 执行探测以支持 Web UI 方案。
# ==================================

"""run.py — 多平台调度入口（M2++ 升级版）。

支持：
    1. 命令行参数 / 交互菜单 二选一 选取要测试的平台
    2. 串行（默认）/ 并行（--parallel）
    3. ProbeMode（standard / deep）
    4. 启动时自动从 OS Keychain 解锁 .env.enc

使用示例：
    python run.py                            # 无参 → 交互菜单选择平台
    python run.py --platforms BlazeAI,Groq   # 指定平台
    python run.py --all                      # 所有平台
    python run.py --all --parallel           # 所有平台并行
    python run.py --platforms BlazeAI --mode deep
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import datetime
from pathlib import Path

# 强制 stdout 使用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 添加项目根目录到 sys.path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))

from core.adapters.base import AdapterRegistry, OpenAIAdapter
from core.analyzer import ResultAnalyzer
from core.config import ConfigManager, ConfigStore
from core.constants import ConfigError, ProbeMode
from core.engine.engine import ProbeEngine
from core.engine.stages import (
    Stage0_Preflight,
    Stage1_FormatDetection,
    Stage2_EndpointDiscovery,
    Stage2_5_ModelAvailabilityCheck,
    Stage3_CapabilityProbing,
    Stage4_LimitsDetection,
    Stage5_StabilityAnalysis,
)
from core.models import ProbeContext
from core.reporter import ReportGenerator
from core.scheduler import PlatformRunResult, PlatformScheduler
from core.secret import SecretResolver
from core.vault import EnvVault, VaultDecryptError, VaultError
from core.probes.basic_chat import BasicChatProbe
from core.probes.streaming import StreamingProbe
from core.probes.tool_calling import ToolCallingProbe
from core.probes.vision import VisionProbe
from core.probes.json_mode import JsonModeProbe
from core.probes.reasoning import ReasoningProbe
from core.probes.web_search import WebSearchProbe
from core.probes.multi_turn import MultiTurnProbe


CONFIG_PATH = project_root / "config" / "user_config.yaml"
REPORTS_DIR = project_root.parent / "reports"
MAX_PASSWORD_RETRIES = 3


# ──────────────────────────────────────────────────────────────────
# 启动阶段：解锁加密保险箱
# ──────────────────────────────────────────────────────────────────

def unlock_vault() -> str | None:
    """启动时解锁加密配置并返回主密码。若配置与注册表不存在则引导首次初始化。"""
    from core.platform_manager import PlatformManager

    env_exists = EnvVault.exists()
    registry_exists = PlatformManager.REGISTRY_PATH.exists()

    if not env_exists and not registry_exists:
        print("======================================================================")
        print("  API 平台探测系统 — 平台注册表加密文件 platforms.enc 不存在")
        print("  系统将引导您进行首次解锁密码设置与初始化...")
        print("======================================================================")
        print()
        
        # 1. 引导设置主密码
        while True:
            try:
                pw1 = getpass.getpass("请设置主密码（至少 6 位，输入不会显示）：")
                if len(pw1) < 6:
                    print("[FAIL] 主密码长度需至少 6 位，请重新输入。", file=sys.stderr)
                    continue
                pw2 = getpass.getpass("请再次输入以确认主密码：")
                if pw1 != pw2:
                    print("[FAIL] 两次输入的密码不一致，请重新输入。", file=sys.stderr)
                    continue
                break
            except (EOFError, KeyboardInterrupt):
                print("\n已取消初始化。", file=sys.stderr)
                return None
        
        # 2. 读取默认配置模板并生成 platforms.enc
        default_template_path = PlatformManager.REGISTRY_PATH.parent / "platforms_default.json"
        import json
        if default_template_path.exists():
            try:
                plaintext_bytes = default_template_path.read_bytes()
                json.loads(plaintext_bytes.decode("utf-8"))
            except Exception as te:
                print(f"[WARNING] 默认模板 platforms_default.json 解析失败: {te}，将初始化为空平台列表。")
                plaintext_bytes = b'{"platforms": []}'
        else:
            plaintext_bytes = b'{"platforms": []}'
            
        try:
            ciphertext = EnvVault.encrypt_bytes(plaintext_bytes, pw1)
            PlatformManager.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            PlatformManager.REGISTRY_PATH.write_bytes(ciphertext)
            print(f"[OK] 首次初始化成功！生成注册表文件：{PlatformManager.REGISTRY_PATH}")
            # 自动缓存到 Keychain
            try:
                EnvVault.save_master_to_keychain(pw1)
                print("[OK] 已自动将最新主密码缓存至 OS Keychain，下次将免密启动")
            except Exception as ke:
                print(f"[WARNING] 密码缓存至 Keychain 失败: {ke}")
            return pw1
        except Exception as ee:
            print(f"[ERROR] 首次初始化加密注册表文件失败: {ee}", file=sys.stderr)
            return None

    # 1. 试 Keychain
    pw = EnvVault.load_master_from_keychain()
    if pw is not None:
        try:
            if registry_exists:
                # 尝试用密码实例化 PlatformManager 验证密码
                PlatformManager(pw)
            else:
                SecretResolver.load_vault(pw)
            print("[OK] 已从 OS Keychain 自动解锁加密配置")
            return pw
        except Exception:
            print(
                "[WARN] OS Keychain 中的主密码与加密文件不匹配，需要重新输入。",
                file=sys.stderr,
            )

    # 2. 终端输入
    for attempt in range(1, MAX_PASSWORD_RETRIES + 1):
        try:
            pw = getpass.getpass(
                f"请输入主密码（剩余 {MAX_PASSWORD_RETRIES - attempt + 1} 次尝试）："
            )
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return None
        try:
            if registry_exists:
                PlatformManager(pw)
            else:
                SecretResolver.load_vault(pw)
            EnvVault.save_master_to_keychain(pw)
            print("[OK] 解锁成功。主密码已缓存到 OS Keychain。")
            return pw
        except Exception:
            print(f"[FAIL] 主密码错误（{attempt}/{MAX_PASSWORD_RETRIES}）。", file=sys.stderr)

    print(
        "\n[ERROR] 主密码尝试次数已用尽。",
        file=sys.stderr,
    )
    return None


# ──────────────────────────────────────────────────────────────────
# 平台选择
# ──────────────────────────────────────────────────────────────────

def interactive_select(all_names: list[str]) -> list[str]:
    """交互菜单选择平台。

    Args:
        all_names: 配置文件里的全部平台名

    Returns:
        用户选中的平台名列表（保持原顺序）
    """
    print()
    print("请选择要测试的平台（输入编号，空格分隔；输入 0 选全部）：")
    for i, name in enumerate(all_names, start=1):
        print(f"  [{i}] {name}")
    print()
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            sys.exit(1)
        if not raw:
            print("[WARN] 至少选择一个平台。")
            continue
        tokens = raw.split()
        if "0" in tokens:
            print(f"已选：全部 {len(all_names)} 个平台")
            return list(all_names)
        try:
            indices = [int(t) for t in tokens]
        except ValueError:
            print("[WARN] 请输入数字编号。")
            continue
        if any(i < 1 or i > len(all_names) for i in indices):
            print(f"[WARN] 编号需在 1~{len(all_names)} 之间。")
            continue
        # 去重保序
        seen: set[int] = set()
        selected = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                selected.append(all_names[i - 1])
        print(f"已选：{', '.join(selected)}")
        return selected


def parse_platforms_arg(arg: str, all_names: list[str]) -> list[str]:
    """解析 --platforms A,B,C，校验每个名字都在 all_names 里。"""
    names = [n.strip() for n in arg.split(",") if n.strip()]
    unknown = [n for n in names if n not in all_names]
    if unknown:
        print(
            f"[ERROR] 配置文件里不存在以下平台：{', '.join(unknown)}",
            file=sys.stderr,
        )
        print(f"        可用平台：{', '.join(all_names)}", file=sys.stderr)
        sys.exit(2)
    return names


# ──────────────────────────────────────────────────────────────────
# 单平台 worker
# ──────────────────────────────────────────────────────────────────

def make_worker(config_manager: ConfigManager, mode: str):
    """工厂函数：返回闭包，绑定 ConfigManager + mode。"""
    from core.probe_runner import run_platform_probe

    async def worker(platform_name: str) -> PlatformRunResult:
        """执行单个平台的完整探测流程。"""
        platform = config_manager.get_platform(platform_name)
        probe_timeouts = config_manager.get_probe_timeouts()
        deep_top_n = config_manager.get_deep_probe_top_n()

        return await run_platform_probe(
            platform=platform,
            mode=mode,
            probe_timeouts=probe_timeouts,
            deep_top_n=deep_top_n,
            reports_dir=REPORTS_DIR,
        )

    return worker


# ──────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run",
        description="API 平台智能探测系统 — 多平台调度入口",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--platforms",
        help="要测试的平台名列表，逗号分隔（如 BlazeAI,Groq）。"
             "若不提供，进入交互菜单。",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="测试配置文件中所有平台",
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="启动 FastAPI Web 服务器与 UI 静态页面",
    )
    p.add_argument(
        "--parallel",
        action="store_true",
        help="并行执行多平台（默认串行）",
    )
    p.add_argument(
        "--mode",
        choices=[m.value for m in ProbeMode],
        default=ProbeMode.STANDARD.value,
        help="探测深度（standard / deep），默认 standard",
    )
    return p


async def run_web_mode() -> int:
    """启动 FastAPI Web 服务端。"""
    import uvicorn
    from web.app import create_app
    from core.platform_manager import PlatformManager
    from core.config import ConfigStore, ConfigManager
    
    # 1. 引导解锁或交互初始化，获取主密码
    pw = unlock_vault()
    if pw is None:
        print("[ERROR] 解锁认证失败，启动中止。", file=sys.stderr)
        return 1
        
    # 2. 初始化 PlatformManager 并保存单例
    try:
        pm = PlatformManager(pw)
    except Exception as e:
        print(f"[ERROR] 实例化 PlatformManager 失败: {e}", file=sys.stderr)
        return 1
        
    # 3. 初始化全局 ConfigManager
    config_path = Path(__file__).resolve().parent / "config" / "user_config.yaml"
    config_store = ConfigStore(config_path)
    config_mgr = ConfigManager(config_store, pm)
    try:
        config_mgr.load()
    except Exception as e:
        print(f"[ERROR] 配置加载失败: {e}", file=sys.stderr)
        return 1
        
    # 动态附加 project_root 给 config_mgr 以便 reports 拼接
    config_mgr.project_root = str(Path(__file__).resolve().parent.parent)

    # 4. 创建 FastAPI App
    app = create_app()
    
    # 注入单例到 app.state 中
    app.state.platform_manager = pm
    app.state.config_manager = config_mgr

    # 5. 启动 Uvicorn API 服务
    print("======================================================================")
    print("  API 平台探测系统 — FastAPI 后端及 UI 服务端已成功拉起")
    print("  请在浏览器中访问 http://127.0.0.1:8080")
    print("======================================================================")
    config = uvicorn.Config(app, host="127.0.0.1", port=8080, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
    return 0


async def run_as_client(selected_platforms: list[str], mode: str) -> int:
    """CLI 客户端代理模式：将探测任务发送给后台服务，并监听流式 SSE 日志直到任务完成。"""
    import httpx
    import json
    
    # 1. 发送触发任务请求
    url_start = "http://127.0.0.1:8080/api/tests/start"
    payload = {"platforms": selected_platforms, "mode": mode}
    
    print(f"[Client] 正在向后台服务触发探测任务 (平台: {', '.join(selected_platforms)}, 模式: {mode})...")
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url_start, json=payload, timeout=10.0)
            if res.status_code == 409:
                print(f"[ERROR] 触发失败：部分或全部平台已经在探测中：{res.json().get('detail')}", file=sys.stderr)
                return 1
            if res.status_code != 200:
                print(f"[ERROR] 触发测试失败 (HTTP {res.status_code}): {res.text}", file=sys.stderr)
                return 1
            
            res_data = res.json()
            started = res_data.get("started", [])
            already_running = res_data.get("already_running", [])
            
            if already_running:
                print(f"[WARN] 部分平台已经在运行中，本次未重复触发：{', '.join(already_running)}")
            if not started:
                print("[INFO] 没有平台被成功触发启动。退出。")
                return 0
                
            print(f"[OK] 成功拉起后台异步任务：{', '.join(started)}")
            print("[Client] 正在订阅后台 SSE 事件流以获取实时进度...")
            print("-" * 70)
            
            # 2. 建立 SSE 长连接流式输出
            url_events = "http://127.0.0.1:8080/api/tests/events"
            pending = set(started)
            failed_platforms = set()
            
            # 使用 httpx stream 获取 SSE
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
            async with httpx.AsyncClient(limits=limits, timeout=None) as stream_client:
                async with stream_client.stream("GET", url_events) as response:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        if line.startswith("data:"):
                            try:
                                event = json.loads(line[5:].strip())
                            except Exception:
                                continue
                            
                            platform = event.get("platform")
                            if platform not in pending:
                                continue
                                
                            status = event.get("status")
                            stage = event.get("stage", "System")
                            msg = event.get("message", "")
                            
                            # 根据状态美化打印
                            if status == "started":
                                print(f"🚀 [{platform}] {msg}")
                            elif status == "running":
                                print(f"⏳ [{platform}] > {stage}: {msg}")
                            elif status == "success":
                                print(f"✅ [{platform}] > {stage}: {msg}")
                            elif status == "completed":
                                score = event.get("score")
                                score_str = f"打分: {score}" if score is not None else "无评分"
                                print(f"🎉 [{platform}] {msg} ({score_str})")
                                pending.discard(platform)
                            elif status in ("error", "failed"):
                                print(f"❌ [{platform}] 探测失败或出错：{msg}")
                                failed_platforms.add(platform)
                                pending.discard(platform)
                            
                            if not pending:
                                break
                                
            print("-" * 70)
            print("[Client] 触发的所有平台探测任务均已在后端执行完毕。")
            if failed_platforms:
                print(f"❌ 探测失败的平台：{', '.join(failed_platforms)}", file=sys.stderr)
                return 1
            print("🎉 所有任务圆满成功！")
            return 0
            
    except Exception as e:
        print(f"[ERROR] 客户端连接后台异常中断: {e}", file=sys.stderr)
        return 1


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 0. 快速检查是否开启 Web 后端
    if args.web:
        return await run_web_mode()

    print("=" * 70)
    print("API 平台智能探测系统 — 多平台调度")
    print("=" * 70)
    print()

    # 1. 尝试以客户端代理模式检查后台服务是否在线
    import httpx
    service_online = False
    try:
        async with httpx.AsyncClient() as check_client:
            res_health = await check_client.get("http://127.0.0.1:8080/health", timeout=1.5)
            if res_health.status_code == 200:
                service_online = True
    except Exception:
        pass

    if service_online:
        print("[INFO] 检测到后台 Web 服务正在运行 (127.0.0.1:8080)，将开启客户端代理模式...")
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("http://127.0.0.1:8080/api/platforms", timeout=5.0)
                if res.status_code != 200:
                    print(f"[ERROR] 从后端获取平台列表失败 (HTTP {res.status_code})。降级为 Headless 模式运行...", file=sys.stderr)
                    service_online = False
                else:
                    all_names = [p["name"] for p in res.json()]
                    if not all_names:
                        print("[ERROR] 后端无可用平台，请先在网页或模板中初始化平台。", file=sys.stderr)
                        return 1
                    
                    # 确定要测试的平台
                    if args.all:
                        selected = list(all_names)
                        print(f"[OK] 已选：全部 {len(selected)} 个平台")
                    elif args.platforms:
                        selected = parse_platforms_arg(args.platforms, all_names)
                        print(f"[OK] 已选：{', '.join(selected)}")
                    else:
                        selected = interactive_select(all_names)
                    
                    # 作为客户端触发并监听
                    return await run_as_client(selected, args.mode)
        except Exception as client_err:
            print(f"[WARNING] 客户端通信异常: {client_err}。将尝试自动降级为 Headless 模式...", file=sys.stderr)
            service_online = False

    # 2. 如果后台服务离线，开启 Headless 本地模式
    if not service_online:
        print("[INFO] 启用本地 Headless 无头模式运行探测任务...")
        print()

        # 1. 解锁加密保险箱
        master_password = unlock_vault()
        if not master_password:
            return 1
        print()

        # 2. 加载平台配置
        if not CONFIG_PATH.exists():
            print(f"[ERROR] 配置文件不存在: {CONFIG_PATH}", file=sys.stderr)
            return 1

        from core.platform_manager import PlatformManager
        platform_manager = PlatformManager(master_password)
        config_store = ConfigStore(CONFIG_PATH)
        config_manager = ConfigManager(config_store, platform_manager)
        try:
            config_manager.load()
        except ConfigError as e:
            print(f"[ERROR] 配置加载失败: {e}", file=sys.stderr)
            return 1

        all_platforms = config_manager.list_platforms()
        all_names = [p.name for p in all_platforms]
        if not all_names:
            print("[ERROR] 配置文件中没有任何平台。", file=sys.stderr)
            return 1
        print(f"[OK] 配置加载成功：共 {len(all_names)} 个平台 ({', '.join(all_names)})")

        # 3. 确定要测试的平台
        if args.all:
            selected = list(all_names)
            print(f"[OK] 已选：全部 {len(selected)} 个平台")
        elif args.platforms:
            selected = parse_platforms_arg(args.platforms, all_names)
            print(f"[OK] 已选：{', '.join(selected)}")
        else:
            selected = interactive_select(all_names)

        # 4. 创建调度器并跑
        worker = make_worker(config_manager, args.mode)
        scheduler = PlatformScheduler(worker)

        if args.parallel and len(selected) > 1:
            summary = await scheduler.run_parallel(selected)
        else:
            summary = await scheduler.run_serial(selected)

        # 5. 汇总
        print()
        print("=" * 70)
        print(f"  调度完成：共 {summary.total} 个平台，"
              f"成功 {summary.succeeded}，失败 {summary.failed}")
        print("=" * 70)
        if summary.failed > 0:
            print("\n失败平台列表：")
            for r in summary.results:
                if not r.success:
                    print(f"  - {r.name}: {r.error_message}")
        print()
        print(f"报告目录：{REPORTS_DIR}")
        return 0 if summary.failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        print("\n[INFO] 已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
