from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rzp_key_id: str = ""
    rzp_key_secret: str = ""
    rzp_webhook_secret: str = "test_webhook_secret"
    database_url: str = "sqlite:///./recoverai.db"
    agent_model: str = "gemini-2.5-flash"
    llm_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    sarvam_api_key: str = ""

    @property
    def has_live_keys(self) -> bool:
        return self.rzp_key_id.startswith("rzp_test_") and bool(self.rzp_key_secret)

    @property
    def has_twilio(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_whatsapp_from)


@lru_cache
def get_settings() -> Settings:
    return Settings()
