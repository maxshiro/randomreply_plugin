from typing import Callable, Optional

from domain.randomization import hit_by_denominator


class RepeatFeature:
    def __init__(self, get_config: Callable[[str, object], object]):
        self.get_config = get_config

    def pick(self, message_text: str) -> Optional[str]:
        if not bool(self.get_config("enable_repeat", False)):
            return None
        if not message_text:
            return None
        if not hit_by_denominator(int(self.get_config("repeat_chance", 100))):
            return None
        return message_text
