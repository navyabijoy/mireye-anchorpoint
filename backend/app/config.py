from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./anchorpoint.db",
        description="The SQLAlchemy connection string. Defaults to a local SQLite database.",
    )
    MIREYE_API_TOKEN: str = Field(
        default="",
        description="The bearer API token for the Mireye Earth API.",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
