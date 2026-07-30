from os import environ
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


def alembic_config(database_url: str) -> Config:
    project_root = Path(
        environ.get("CLOUDFILEFLOW_PROJECT_ROOT", Path(__file__).resolve().parents[2])
    )
    configuration = Config(project_root / "alembic.ini")
    configuration.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return configuration


def upgrade_database(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def verify_database_revision(engine: Engine, database_url: str) -> None:
    configuration = alembic_config(database_url)
    expected = ScriptDirectory.from_config(configuration).get_current_head()
    with engine.connect() as connection:
        actual = MigrationContext.configure(connection).get_current_revision()
    if actual != expected:
        raise RuntimeError(
            "Database migration is not current. Run 'alembic upgrade head' before startup."
        )
