# -*- coding: utf-8 -*-
"""便捷入口:在 stock-assistant 目录下运行 `python main.py report` 等命令。"""
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "quote.py")
sys.argv[0] = SCRIPT
runpy.run_path(SCRIPT, run_name="__main__")
