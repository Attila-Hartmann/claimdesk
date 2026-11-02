from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # repo root
DATA = ROOT / "data"


class Endpoint(BaseModel):
    """An OpenAI-compatible model endpoint (DeepSeek, a vLLM server on Modal, Bedrock's OpenAI-compatible API...)."""

    name: str
    base_url: str
    model: str
    api_key: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ".env"), extra="ignore")

    # champion: the frontier model in production today; challenger: the fine-tuned open-weight model being rolled out
    champion_base_url: str = "https://api.deepseek.com/v1"
    champion_model: str = "deepseek-chat"
    champion_api_key: str = ""
    challenger_base_url: str = ""
    challenger_model: str = "claimdesk-extractor"
    challenger_api_key: str = "not-needed"
    challenger_key_param: str = ""  # AWS: SSM SecureString holding the challenger key

    store_bucket: str = ""  # S3 bucket on AWS; empty = local folder data/store
    queue_url: str = ""  # SQS queue on AWS; empty = process uploads inline
    origin_secret: str = ""  # header CloudFront sends to the function URL
    reviews_readonly: bool = False  # public demo: visitors can upload, but not move the canary statistics
    daily_upload_limit: int = 40
    tesseract_cmd: str = "tesseract"
    tessdata_dir: str = ""
    mlflow_tracking_uri: str = f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}"  # SQLite backend: runs + model registry

    def endpoint(self, name: str) -> Endpoint:
        return Endpoint(name=name, base_url=getattr(self, f"{name}_base_url"), model=getattr(self, f"{name}_model"),
                        api_key=getattr(self, f"{name}_api_key"))


@lru_cache
def settings() -> Settings:
    s = Settings()
    if s.challenger_key_param:  # keep the secret out of the function's environment variables
        import boto3

        s.challenger_api_key = boto3.client("ssm").get_parameter(Name=s.challenger_key_param, WithDecryption=True)["Parameter"]["Value"]
    return s
