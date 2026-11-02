from dwellcall.application import create_app
from dwellcall.database.connection import create_database_engine
from dwellcall.settings import ApiSettings

settings = ApiSettings()
database_engine = create_database_engine(settings, service_name="api")
app = create_app(settings, database_engine)
