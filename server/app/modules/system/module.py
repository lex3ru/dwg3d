from app.core.module import Module
from app.modules.system.routes import router

module = Module(name="system", title="Система", routers=[router])
