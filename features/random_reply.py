import random
from typing import Callable, Dict, Optional, Tuple

from ..domain.randomization import choose_weighted, clamp01, hit_by_denominator
from ..infra.media.image_service import ImageService
from ..infra.repo.photo_repo import PhotoRepo
from ..infra.repo.text_repo import TextRepo


class RandomReplyFeature:
    def __init__(
        self,
        text_repo: TextRepo,
        photo_repo: PhotoRepo,
        image_service: ImageService,
        get_config: Callable[[str, object], object],
    ):
        self.text_repo = text_repo
        self.photo_repo = photo_repo
        self.image_service = image_service
        self.get_config = get_config
        self.photo_fail_streak: Dict[str, int] = {}

    def pick(self, group_id: str, force_trigger: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        chance = int(self.get_config("reply_chance", 100))
        if not force_trigger and not hit_by_denominator(chance):
            return None, None, None

        text_pool, text_weights = self.text_repo.load_pool(group_id)
        photo_pool = self.photo_repo.load_available()
        has_text = len(text_pool) > 0
        has_photo = len(photo_pool) > 0
        if not has_text and not has_photo:
            return None, None, None

        text_ratio = clamp01(float(self.get_config("text_reply_ratio", 0.6)))
        weighted_ratio = clamp01(float(self.get_config("weighted_text_ratio", 0.25)))

        choose_text = has_text and (not has_photo or random.random() < text_ratio)
        if choose_text:
            if random.random() < weighted_ratio:
                picked = choose_weighted(text_pool, text_weights)
                if picked:
                    return picked, "text", None
            return random.choice(text_pool), "text", None

        image_name = random.choice(photo_pool)
        path, source = self.image_service.resolve_photo_path(image_name)
        if path:
            self.photo_fail_streak[image_name] = 0
            return path, "photo", source

        streak = self.photo_fail_streak.get(image_name, 0) + 1
        self.photo_fail_streak[image_name] = streak
        threshold = int(self.get_config("photo_fail_threshold", 3))
        if streak >= threshold:
            self.photo_repo.mark_invalid(image_name, True)
        return None, None, None
