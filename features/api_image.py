from typing import Callable, Optional

from ..domain.randomization import hit_by_denominator
from ..infra.media.image_service import ImageService


class ApiImageFeature:
    def __init__(self, image_service: ImageService, get_config: Callable[[str, object], object]):
        self.image_service = image_service
        self.get_config = get_config

    def pick(self, force_trigger: bool = False) -> Optional[str]:
        if not bool(self.get_config("enable_api_image", False)):
            return None
        if not force_trigger and not hit_by_denominator(int(self.get_config("api_image_chance", 100))):
            return None
        return self.image_service.fetch_api_image_reference()
