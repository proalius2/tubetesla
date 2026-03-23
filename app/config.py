"""
Configuration module for TubeTesla application.
Centralizes all configuration settings and environment variables.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    """Application settings with default values."""
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    
    # Video processing settings
    default_resolution: int = 720
    default_quality: int = 85
    default_fps_limit: int = 30
    max_frame_queue_size: int = 5
    
    # Audio sync settings
    audio_sync_default: float = 0.0
    audio_sync_min: float = -2.0
    audio_sync_max: float = 2.0
    audio_sync_step: float = 0.05
    
    # YouTube settings
    youtube_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Static files directory
    static_dir: str = "app/static"
    templates_dir: str = "app/templates"
    
    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables."""
        return cls(
            host=os.getenv("TUBETESLA_HOST", "0.0.0.0"),
            port=int(os.getenv("TUBETESLA_PORT", "8000")),
            debug=os.getenv("TUBETESLA_DEBUG", "true").lower() == "true",
            default_resolution=int(os.getenv("TUBETESLA_RESOLUTION", "720")),
            default_quality=int(os.getenv("TUBETESLA_QUALITY", "85")),
        )


# Global settings instance
settings = Settings.from_env()
