import math


def compute_w0(msg_length: int, max_length: int) -> float:
    if max_length <= 1:
        return 0.0
    l = max(1, msg_length)
    if l >= max_length:
        return 0.0
    return 0.5 * (1.0 - ((l - 1.0) / (max_length - 1.0)))


def compute_updated_weight(w0: float, alpha: float, count: int) -> float:
    return w0 + (1.0 - w0) * (1.0 - math.exp(-alpha * (count - 1)))
