"""Configuration du serveur web, lue et vérifiée une fois au démarrage (variables d'environnement, puis .env).

Obligatoires : RLPI_PUBLIC_URL, RLPI_SECRET, DATABASE_URL, REDIS_URL, S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY.
Le serveur refuse de démarrer s'il en manque une (message avec les noms seulement, jamais les valeurs), ou si
RLPI_DEV_LOGIN=1 alors que RLPI_PUBLIC_URL est en https:// (production).

Les connexions (Postgres, Redis, Garage) restent ouvertes par rlpi.store, qui lit les mêmes variables : le worker
s'en sert aussi, sans ce module.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rlpi.config import ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", case_sensitive=False)

    public_url: str = Field(validation_alias="RLPI_PUBLIC_URL", description="ex. https://rlpi.lainox.quest")
    secret: str = Field(validation_alias="RLPI_SECRET", min_length=16)
    database_url: str = Field(validation_alias="DATABASE_URL")
    redis_url: str = Field(validation_alias="REDIS_URL")
    s3_endpoint: str = Field(validation_alias="S3_ENDPOINT")
    s3_access_key: str = Field(validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(validation_alias="S3_SECRET_KEY")
    dev_login: bool = Field(default=False, validation_alias="RLPI_DEV_LOGIN")
    web_dist: Path = Field(default=ROOT / "web" / "dist", validation_alias="RLPI_WEB_DIST")

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        # Espaces et guillemets collés par erreur avec la valeur dans Coolify (comme rlpi.store.env)
        return v.strip().strip("\"'").strip() if isinstance(v, str) else v

    @field_validator("public_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("doit commencer par http:// ou https://")
        return v.rstrip("/")

    @model_validator(mode="after")
    def _no_dev_login_in_production(self) -> Settings:
        if self.dev_login and self.https:
            raise ValueError(
                "RLPI_DEV_LOGIN=1 est interdit quand RLPI_PUBLIC_URL est en https:// (production) : retirer cette "
                "variable."
            )
        return self

    @property
    def https(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def origin(self) -> str:
        """Origine attendue des formulaires et des requêtes d'écriture (protection CSRF)."""
        from urllib.parse import urlparse

        u = urlparse(self.public_url)
        return f"{u.scheme}://{u.netloc}".lower()


def describe(e: ValidationError) -> str:
    """Erreurs de configuration, avec les noms des variables et jamais leurs valeurs."""
    names = {n: f.validation_alias for n, f in Settings.model_fields.items()}
    out = []
    for err in e.errors():
        loc = str(err["loc"][0]) if err["loc"] else ""
        name = names.get(loc, loc) or "configuration"
        out.append(f"{name} : {'manquante' if err['type'] == 'missing' else err['msg']}")
    return "Configuration du serveur invalide : " + " ; ".join(out)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # valeurs lues dans l'environnement
    except ValidationError as e:
        raise SystemExit(describe(e)) from None
