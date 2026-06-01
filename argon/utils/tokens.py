from typing import Any, Dict, Optional, Tuple


PRECISION_BUDGET_PROFILES = {
    'custom': {'tokens': None, 'full_code_ratio': 0.72, 'expansion_items': 8},
    'micro': {'tokens': 1500, 'full_code_ratio': 0.62, 'expansion_items': 3},
    'standard': {'tokens': 4096, 'full_code_ratio': 0.72, 'expansion_items': 8},
    'deep': {'tokens': 8192, 'full_code_ratio': 0.80, 'expansion_items': 12},
}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class TokenCounter:
    def __init__(self, model: str = "gpt-4.1", strict: bool = False, has_tiktoken: Optional[bool] = None, tiktoken_mod=None):
        self.model = model
        self.encoder = None
        self._tiktoken = tiktoken_mod

        if has_tiktoken is None:
            try:
                import tiktoken as _t
                self._tiktoken = _t
                has_tiktoken = True
            except ImportError:
                has_tiktoken = False

        if has_tiktoken and self._tiktoken is not None:
            try:
                self.encoder = self._tiktoken.encoding_for_model(model)
            except Exception:
                try:
                    self.encoder = self._tiktoken.get_encoding("o200k_base")
                except Exception:
                    self.encoder = None
        if strict and self.encoder is None:
            raise RuntimeError(
                "Precision mode requires tiktoken for real token budgets. "
                "Install it with: pip install tiktoken"
            )

    def count(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        return estimate_tokens(text)


def resolve_precision_budget(max_tokens: int, budget_profile: str = 'custom') -> Tuple[int, Dict[str, Any]]:
    profile_name = (budget_profile or 'custom').lower().strip()
    if profile_name not in PRECISION_BUDGET_PROFILES:
        raise ValueError(
            "budget_profile must be one of: "
            + ", ".join(sorted(PRECISION_BUDGET_PROFILES))
        )
    profile = dict(PRECISION_BUDGET_PROFILES[profile_name])
    tokens = profile.get('tokens')
    resolved = int(tokens if tokens is not None else max_tokens)
    profile['name'] = profile_name
    profile['tokens'] = resolved
    return resolved, profile
