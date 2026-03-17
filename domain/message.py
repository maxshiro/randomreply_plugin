from dataclasses import dataclass


@dataclass
class MessageContext:
    platform: str
    platform_name: str
    group_id: str
    sender_id: str
    user_id: str
    umo: str
    message_text: str
    date_str: str
    time_hms: str
    timestamp: str
    has_image: bool
    is_at_bot: bool
