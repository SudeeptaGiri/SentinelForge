"""Application configuration for legacy order service."""

import os


class Config:
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "legacy-insecure-secret-key-12345")
    DATABASE_PATH = os.getenv("DATABASE_PATH", "/var/lib/orders.db")
    PORT = int(os.getenv("PORT", 8080))
