from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None
    mongodb_database: str
    simulation_backend: str
    sofa_scene_path: str
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    coach_provider: str = "auto"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    sentry_dsn: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            mongodb_uri=os.getenv("SURGE_PREP_MONGODB_URI"),
            mongodb_database=os.getenv("SURGE_PREP_MONGODB_DATABASE", "surge_prep"),
            simulation_backend=os.getenv("SURGE_PREP_SIMULATION_BACKEND", "sofa"),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("SURGE_PREP_OPENAI_MODEL", "gpt-4o-mini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None,
            gemini_model=os.getenv("SURGE_PREP_GEMINI_MODEL", "gemini-2.0-flash"),
            coach_provider=os.getenv("SURGE_PREP_COACH_PROVIDER", "auto"),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
            elevenlabs_voice_id=os.getenv("SURGE_PREP_ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            sentry_dsn=os.getenv("SENTRY_DSN") or None,
            sofa_scene_path=os.getenv(
                "SURGE_PREP_SOFA_SCENE", "../simulation/sofa_scene.py"
            ),
        )
