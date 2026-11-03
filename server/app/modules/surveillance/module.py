from app.core.module import Module
from app.modules.surveillance.analytics import router

module = Module(name="surveillance", title="Видеонаблюдение", routers=[router])
