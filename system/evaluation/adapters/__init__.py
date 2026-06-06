from .base import ModelAdapter, EmbeddingResult, DecodeResult
from .multi_embedding import evaluate_double_embedding, MultiEmbeddingResult

def get_available_adapters() -> dict:
    from system.evaluation.runtime import PROJECT_ROOT
    adapters = {}
    sep_ckpt = PROJECT_ROOT / 'weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth'
    wg_ckpt  = PROJECT_ROOT / 'weights/mea/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth'
    if sep_ckpt.exists():
        from .sepmark_adapter import SepMarkModelAdapter
        adapters['SepMark'] = SepMarkModelAdapter
    if wg_ckpt.exists():
        from .waveguard_adapter import WaveGuardModelAdapter
        adapters['WaveGuard'] = WaveGuardModelAdapter
    return adapters
