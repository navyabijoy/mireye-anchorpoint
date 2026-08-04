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
    OPENAI_API_KEY: str = Field(
        default="",
        description="OpenAI API Key for Agent pipeline.",
    )
    AGENT_MODEL: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for agentic pipeline (e.g. gpt-4o-mini).",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
