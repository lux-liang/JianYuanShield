from .base import ModelAdapter, EmbeddingResult, DecodeResult
from .multi_embedding import evaluate_double_embedding, MultiEmbeddingResult

def get_available_adapters() -> dict:
    from system.evaluation.runtime import PROJECT_ROOT
    from pathlib import Path as _P

    adapters = {}
    sep_ckpt = PROJECT_ROOT / "weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth"
    wg_ckpt  = PROJECT_ROOT / "weights/mea/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"

    if sep_ckpt.exists():
        from .sepmark_adapter import SepMarkModelAdapter
        adapters["SepMark"] = SepMarkModelAdapter

    if wg_ckpt.exists():
        from .waveguard_adapter import WaveGuardModelAdapter
        adapters["WaveGuard"] = WaveGuardModelAdapter

    # LIDMark: use latest checkpoint from seed1
    s1_dir = _P("/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark/seed_checkpoints/s1")
    if s1_dir.exists() and list(s1_dir.glob("checkpoint_epoch_*.pth")):
        from .lidmark_adapter import LIDMarkAdapter
        adapters["LIDMark"] = LIDMarkAdapter

    # KAD-Net: use latest EC checkpoint
    kadnet_runs = _P("/data1/luxliang/work/vpsg_competition_candidates/runs/kadnet/results/ST/128")
    if kadnet_runs.exists():
        for run in sorted(kadnet_runs.iterdir(), reverse=True):
            if (run / "models").exists() and list((run / "models").glob("EC_*.pth")):
                from .kadnet_adapter import KADNetAdapter
                adapters["KAD-Net"] = KADNetAdapter
                break

    # HiDDeN: 30-bit, 300-epoch CelebA+noise training
    try:
        from .hidden_adapter import _ACTIVE_OPTIONS, _ACTIVE_CKPT, HiDDeNAdapter
        if _ACTIVE_OPTIONS.exists() and _ACTIVE_CKPT is not None and _ACTIVE_CKPT.exists():
            adapters["HiDDeN"] = HiDDeNAdapter
    except Exception:
        pass

    return adapters
