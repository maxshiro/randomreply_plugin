import random
from typing import Callable, Optional, Tuple

from domain.randomization import choose_weighted_candidate


class AtMessageFeature:
    def __init__(
        self,
        get_config: Callable[[str, object], object],
        pick_random: Callable[[str, bool], Tuple[Optional[str], Optional[str], Optional[str]]],
        pick_api_image: Callable[[bool], Optional[str]],
    ):
        self.get_config = get_config
        self.pick_random = pick_random
        self.pick_api_image = pick_api_image

    def pick(self, group_id: str, message_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if not bool(self.get_config("enable_at_handler", True)):
            return None, None, None

        candidates: list[tuple[tuple[str, str, Optional[str]], int]] = []

        reply, reply_type, source = self.pick_random(group_id, True)
        if reply and reply_type:
            candidates.append(((reply_type, reply, source), int(self.get_config("at_random_reply_weight", 40))))

        if bool(self.get_config("enable_repeat", False)) and message_text:
            candidates.append((("text", message_text, "repeat"), int(self.get_config("at_repeat_weight", 20))))

        api_ref = self.pick_api_image(True)
        if api_ref:
            candidates.append((("photo", api_ref, "api"), int(self.get_config("at_api_image_weight", 20))))

        fixed_messages = [str(x).strip() for x in self.get_config("at_fixed_messages", ["我在"]) if str(x).strip()]
        if fixed_messages:
            candidates.append(
                (("text", random.choice(fixed_messages), "fixed"), int(self.get_config("at_fixed_message_weight", 20)))
            )

        picked = choose_weighted_candidate(candidates)
        if not picked:
            return None, None, None
        return picked
