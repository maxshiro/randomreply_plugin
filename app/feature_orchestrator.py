import datetime as dt
import random
from typing import Callable, Dict, List, Optional, Tuple

from ..domain.randomization import clamp01
from ..features.api_image import ApiImageFeature
from ..features.at_message import AtMessageFeature
from ..features.random_reply import RandomReplyFeature
from ..features.repeat import RepeatFeature


class FeatureOrchestrator:
    def __init__(
        self,
        get_config: Callable[[str, object], object],
        random_reply_feature: RandomReplyFeature,
        repeat_feature: RepeatFeature,
        api_image_feature: ApiImageFeature,
    ):
        self.get_config = get_config
        self.random_reply_feature = random_reply_feature
        self.repeat_feature = repeat_feature
        self.api_image_feature = api_image_feature
        self.at_feature = AtMessageFeature(
            get_config=get_config,
            pick_random=self.random_reply_feature.pick,
            pick_api_image=self.api_image_feature.pick,
        )

    def decide_on_message(self, group_id: str, message_text: str, is_at_bot: bool) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if is_at_bot and bool(self.get_config("enable_at_handler", True)):
            return self.at_feature.pick(group_id=group_id, message_text=message_text)

        candidates: List[Tuple[str, str, Optional[str]]] = []
        reply, reply_type, source = self.random_reply_feature.pick(group_id=group_id, force_trigger=False)
        if reply and reply_type:
            candidates.append((reply, reply_type, source))

        repeat_text = self.repeat_feature.pick(message_text)
        if repeat_text:
            candidates.append((repeat_text, "text", "repeat"))

        if not candidates:
            return None, None, None
        return random.choice(candidates)

    def in_timestamp_window(self, now: dt.datetime) -> bool:
        start_hour = int(self.get_config("timestamp_active_start_hour", 7))
        end_hour = int(self.get_config("timestamp_active_end_hour", 22))
        h = now.hour
        if start_hour == end_hour:
            return True
        if start_hour < end_hour:
            return start_hour <= h < end_hour
        return h >= start_hour or h < end_hour

    def decide_on_timestamp(self, group_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        candidates: List[Tuple[str, str, Optional[str]]] = []

        if bool(self.get_config("timestamp_enable_main_reply", True)):
            reply, reply_type, source = self.random_reply_feature.pick(group_id=group_id, force_trigger=True)
            if reply and reply_type:
                candidates.append((reply, reply_type, source))

        if bool(self.get_config("timestamp_enable_api_image", True)):
            api_ref = self.api_image_feature.pick(force_trigger=True)
            if api_ref:
                candidates.append((api_ref, "photo", "api"))

        if not candidates:
            return None, None, None
        return random.choice(candidates)

    def timestamp_should_trigger(self) -> bool:
        prob = clamp01(float(self.get_config("timestamp_reply_probability", 0.01)))
        return random.random() < prob
