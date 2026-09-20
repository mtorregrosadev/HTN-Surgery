from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None
    mongodb_database: str
    simulation_backend: str
    sofa_scene_path: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            mongodb_uri=os.getenv("SURGE_PREP_MONGODB_URI"),
            mongodb_database=os.getenv("SURGE_PREP_MONGODB_DATABASE", "surge_prep"),
            simulation_backend=os.getenv("SURGE_PREP_SIMULATION_BACKEND", "sofa"),
            sofa_scene_path=os.getenv(
                "SURGE_PREP_SOFA_SCENE", "../simulation/sofa_scene.py"
            ),
        )
