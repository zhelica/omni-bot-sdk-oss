import sys
from pathlib import Path


def get_model_path(model_name):
    """
    获取 yolo 模型文件的绝对路径，兼容源码和打包环境。
    双重兜底：优先打包目录，找不到则回退到源码目录。
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
        model_path = base_dir / model_name
        if model_path.exists():
            return str(model_path)
        # fallback: 回退到源码目录（开发时可能有用）
        fallback = Path(__file__).resolve().parent / "models" / model_name
        if fallback.exists():
            return str(fallback)
        # 最终返回原路径，由调用方决定如何处理
        return str(model_path)
    else:
        base_dir = Path(__file__).resolve().parent
        model_path = base_dir / "models" / model_name
        return str(model_path)
