
# -*- mode: python ; coding: utf-8 -*-
"""打包：默认 Tk 界面；PySide6 可用时支持 --ui=qt。

排除体积大且用不到的组件：WebEngine、多媒体、3D、图表、网络诊断等。
"""
import os
from PyInstaller.utils.hooks import collect_submodules

# SPEC 位于 packaging/ 下，项目根是它的上一级
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

hiddenimports = ["PIL._tkinter_finder"]
hiddenimports += collect_submodules("PySide6.QtCore")
hiddenimports += collect_submodules("PySide6.QtGui")
hiddenimports += collect_submodules("PySide6.QtWidgets")

EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools", "PySide6.QtAxContainer", "PySide6.QtRemoteObjects",
    "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "tkinter.test", "test", "unittest", "pydoc_data",
    "numpy", "pandas", "matplotlib", "scipy",
]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoRename115",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoRename115",
)
