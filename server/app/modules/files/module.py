from app.core.module import Module
from app.modules.files.routes import router

module = Module(name="files", title="Файлы", routers=[router])
