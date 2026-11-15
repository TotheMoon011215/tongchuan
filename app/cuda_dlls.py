"""把 pip 安装的 NVIDIA CUDA 运行库（cublas / cudnn / cudart）加进 DLL 搜索路径。

机器上通常只装了显卡驱动，没有 CUDA Toolkit；CTranslate2 推理时会找不到
cublas64_12.dll。把 pip 包 nvidia-*-cu12 里的 bin 目录注册进来即可，无需管理员权限。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def setup_cuda_dlls() -> list[str]:
    global _done
    if _done:
        return []
    _done = True
    if sys.platform != "win32":
        return []

    roots: list[Path] = []
    try:
        import site

        for p in site.getsitepackages():
            roots.append(Path(p))
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(Path(user_site))
    except Exception:
        pass
    # 兜底：直接从已知解释器位置推
    roots.append(Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages")

    added: list[str] = []
    seen: set[str] = set()
    for root in roots:
        nv = root / "nvidia"
        if not nv.is_dir() or str(nv) in seen:
            continue
        seen.add(str(nv))
        for sub in sorted(nv.iterdir()):
            bindir = sub / "bin"
            if not bindir.is_dir():
                continue
            try:
                os.add_dll_directory(str(bindir))
            except Exception:
                pass
            os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(bindir))
    return added
