# -*- coding: utf-8 -*-
"""run_web.py — 转发启动至 run.py --web（向下兼容）。

修改历史 (Revision History)
==================================
版本: v1.1.0
日期: 2026-06-16
修改说明: 重构启动流程，直接转发至 run.py --web 执行统一解锁与服务挂载。
"""
import sys
from pathlib import Path

# 将项目根目录加入 python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from api_probe_system.run import main

if __name__ == "__main__":
    sys.exit(main(["--web"]))
