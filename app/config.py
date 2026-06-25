import json
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Civic AI Survey Backend"
    DATABASE_URL: str
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000"]
    PORT: int = 4000
    HOST: str = "127.0.0.1"
    LM_STUDIO_URL: str = "http://localhost:1234/v1/chat/completions"
    LLM_PROVIDER: str = "lmstudio"
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_MODEL: str = "gemini-1.5-flash"
    AWS_BEDROCK_MODEL: str = "anthropic.claude-3-sonnet-20240229-v1:0"
    
    # JWT & Authentication configuration
    JWT_SECRET_KEY: str = "secret-key-change-in-production-for-saarthi"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str) and v.startswith("[") and v.endswith("]"):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
