from app.core.module import Module
from app.modules.journal.routes import router

module = Module(name="journal", title="Журнал", routers=[router])
