# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['server.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('static', 'static'),
        # Los prompts se leen en runtime desde PROMPTS_DIR — sin esto el
        # ejecutable empaquetado falla al importar services.prompt_registry.
        ('prompts', 'prompts'),
        ('scraper.py', '.'),
        ('live_transcriber.py', '.'),
    ],
    hiddenimports=[
        'config',
        'routers',
        'routers.chat',
        'routers.export',
        'routers.live',
        'routers.pages',
        'routers.pdfs',
        'routers.sesiones',
        'services',
        'services.docx',
        'services.groq',
        'services.orchestrator',
        'services.pdf',
        'services.prompt_registry',
        'services.sse',
        'services.tools',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.main',
        'anyio',
        'anyio._backends._asyncio',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='server',
    debug=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='server',
)
