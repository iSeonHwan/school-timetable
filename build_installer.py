"""
설치 프로그램 빌드 스크립트 (macOS / Windows)

사용법:
    python3 build_installer.py          # 현재 플랫폼용으로 빌드
    python3 build_installer.py --mac    # macOS .app 빌드 (macOS에서만)
    python3 build_installer.py --win    # Windows .exe 빌드 (Windows에서만)
    python3 build_installer.py --dmg    # macOS .app + DMG 생성

사전 설치:
    pip install pyinstaller
    macOS DMG 생성 시: pip install dmgbuild
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "SchoolTimetable"
APP_NAME_KR = "학교시간표관리"
ENTRY_SCRIPT = "main.py"
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
INSTALLER_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "installer_output")
VERSION = "1.0.0"

# PyInstaller hidden imports needed for SQLAlchemy + PyQt6
HIDDEN_IMPORTS = [
    # SQLAlchemy
    "sqlalchemy.sql.default_comparator",
    "sqlalchemy.ext.declarative",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "psycopg2",
    # PyQt6 plugins
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    # reportlab
    "reportlab",
    "reportlab.pdfbase._fontdata",
    "reportlab.pdfbase.ttfonts",
    "reportlab.graphics.shapes",
    "reportlab.graphics.widgets",
    "reportlab.lib.utils",
    # openpyxl
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    # core modules
    "core",
    "core.generator",
    "core.change_logger",
    "database",
    "database.models",
    "database.connection",
    "config",
    "ui",
    "ui.main_window",
    "ui.feedback",
    "ui.setup",
    "ui.setup.class_setup",
    "ui.setup.teacher_setup",
    "ui.setup.subject_setup",
    "ui.setup.room_setup",
    "ui.timetable",
    "ui.timetable.class_view",
    "ui.timetable.teacher_view",
    "ui.timetable.neis_grid",
    "ui.timetable.edit_dialog",
    "ui.timetable.request_list",
    "ui.calendar",
    "ui.calendar.calendar_widget",
    "ui.history",
    "ui.history.history_view",
    "ui.export",
    "ui.export.pdf_export",
    "ui.export.neis_export",
]

# Data files to include (src relative path -> dest relative dir)
DATAS = [
    # Add data files here if needed, e.g.:
    # ("fonts/NanumGothic.ttf", "fonts"),
]

COLLECTS = [
    "PyQt6",
]


def clean():
    """이전 빌드 결과물 삭제"""
    for d in [BUILD_DIR, DIST_DIR, INSTALLER_OUTPUT_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
    spec_file = os.path.join(PROJECT_ROOT, f"{APP_NAME}.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)


def build_with_pyinstaller(platform_target=None):
    """PyInstaller로 실행 파일 빌드"""
    if platform_target is None:
        platform_target = platform.system()

    # Clean slate
    spec_file = os.path.join(PROJECT_ROOT, f"{APP_NAME}.spec")
    for f in [spec_file]:
        if os.path.exists(f):
            os.remove(f)

    # Build the command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                        # One folder mode (faster startup)
        f"--name={APP_NAME}",
        "--clean",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
    ]

    # Platform-specific options
    if platform_target == "Darwin":
        cmd.append("--windowed")           # macOS .app bundle
        # Icon (optional — use if icon file exists)
        icon_path = os.path.join(PROJECT_ROOT, "installer", "icon.icns")
        if os.path.exists(icon_path):
            cmd.append(f"--icon={icon_path}")
        # Add plist info
        cmd.append(f"--osx-bundle-identifier=com.school.timetable")

    elif platform_target == "Windows":
        cmd.append("--windowed")           # No console window
        icon_path = os.path.join(PROJECT_ROOT, "installer", "icon.ico")
        if os.path.exists(icon_path):
            cmd.append(f"--icon={icon_path}")

    # Hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Data files
    for src, dest in DATAS:
        src_path = os.path.join(PROJECT_ROOT, src)
        if os.path.exists(src_path):
            cmd.extend(["--add-data", f"{src_path}{os.pathsep}{dest}"])

    # Collects
    for coll in COLLECTS:
        cmd.extend(["--collect-all", coll])

    # Exclude unnecessary heavy modules
    excludes = ["tkinter", "unittest", "test", "pytest", "setuptools", "pip"]
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    # Entry point
    cmd.append(os.path.join(PROJECT_ROOT, ENTRY_SCRIPT))

    print(f"[빌드] PyInstaller 실행 중...")
    print(f"[명령] {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("[오류] PyInstaller 빌드 실패")
        return False

    print(f"[완료] 빌드 성공 → {os.path.join(DIST_DIR, APP_NAME)}")
    return True


def create_dmg():
    """macOS DMG 파일 생성"""
    if platform.system() != "Darwin":
        print("[오류] DMG 생성은 macOS에서만 가능합니다.")
        return False

    app_path = os.path.join(DIST_DIR, f"{APP_NAME}.app")
    if not os.path.exists(app_path):
        print("[오류] .app 번들이 없습니다. 먼저 빌드해 주세요.")
        return False

    # Check if dmgbuild is installed
    try:
        import dmgbuild
    except ImportError:
        print("[안내] dmgbuild 미설치 → pip install dmgbuild")
        print("[안내] 대신 hdiutil로 기본 DMG 생성합니다.")
        return _create_dmg_via_hdiutil(app_path)

    os.makedirs(INSTALLER_OUTPUT_DIR, exist_ok=True)
    dmg_path = os.path.join(INSTALLER_OUTPUT_DIR, f"{APP_NAME}_{VERSION}.dmg")

    try:
        dmgbuild.build_dmg(
            filename=dmg_path,
            volume_name=f"{APP_NAME} {VERSION}",
            settings={
                "app": app_path,
                "files": [app_path],
                "icon_size": 80,
                "window_rect": ((100, 100), (500, 400)),
                "icon_locations": {
                    f"{APP_NAME}.app": (140, 140),
                    "Applications": (360, 140),
                },
                "symlinks": {"Applications": "/Applications"},
            },
        )
        print(f"[완료] DMG 생성됨 → {dmg_path}")
        return True
    except Exception as e:
        print(f"[오류] DMG 생성 실패: {e}")
        return _create_dmg_via_hdiutil(app_path)


def _create_dmg_via_hdiutil(app_path):
    """hdiutil을 사용한 기본 DMG 생성"""
    os.makedirs(INSTALLER_OUTPUT_DIR, exist_ok=True)
    dmg_path = os.path.join(INSTALLER_OUTPUT_DIR, f"{APP_NAME}_{VERSION}.dmg")
    dmg_temp = os.path.join(BUILD_DIR, "dmg_temp")

    if os.path.exists(dmg_temp):
        shutil.rmtree(dmg_temp)
    os.makedirs(dmg_temp)

    # Copy .app and create symlink to /Applications
    shutil.copytree(app_path, os.path.join(dmg_temp, f"{APP_NAME}.app"))
    subprocess.run(["ln", "-s", "/Applications", os.path.join(dmg_temp, "Applications")])

    # Remove old dmg if exists
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    result = subprocess.run([
        "hdiutil", "create",
        "-volname", f"{APP_NAME} {VERSION}",
        "-srcfolder", dmg_temp,
        "-ov", "-format", "UDZO",
        dmg_path,
    ])

    shutil.rmtree(dmg_temp)

    if result.returncode == 0:
        print(f"[완료] DMG 생성됨 → {dmg_path}")
        return True
    else:
        print("[오류] DMG 생성 실패")
        return False


def create_windows_installer():
    """Windows NSIS 또는 ZIP 패키지 생성"""
    if platform.system() != "Windows":
        print("[안내] Windows용 패키징은 Windows 환경에서 실행해 주세요.")
        print("[안내] 대신 ZIP 아카이브를 생성합니다.")

    os.makedirs(INSTALLER_OUTPUT_DIR, exist_ok=True)
    exe_dir = os.path.join(DIST_DIR, APP_NAME)

    if not os.path.exists(exe_dir):
        print("[오류] 빌드 결과물이 없습니다. 먼저 빌드해 주세요.")
        return False

    # ZIP packaging
    import zipfile
    zip_path = os.path.join(INSTALLER_OUTPUT_DIR, f"{APP_NAME}_{VERSION}_Windows.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(exe_dir):
            for f in files:
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, DIST_DIR)
                zf.write(abs_path, rel_path)

    print(f"[완료] ZIP 패키지 생성됨 → {zip_path}")
    return True


def print_build_info():
    """빌드 환경 정보 출력"""
    print("=" * 60)
    print(f"  {APP_NAME_KR} 설치 프로그램 빌더  v{VERSION}")
    print("=" * 60)
    print(f"  플랫폼:   {platform.system()} {platform.release()}")
    print(f"  Python:   {sys.version}")
    print(f"  아키텍처: {platform.machine()}")
    print(f"  출력 디렉터리: {DIST_DIR}")
    print("=" * 60)
    print()


def main():
    parser = argparse.ArgumentParser(description="학교 시간표 관리 시스템 설치 프로그램 빌더")
    parser.add_argument("--mac", action="store_true", help="macOS .app 빌드")
    parser.add_argument("--win", action="store_true", help="Windows .exe 빌드")
    parser.add_argument("--dmg", action="store_true", help="macOS DMG 생성 (.app 빌드 포함)")
    parser.add_argument("--clean", action="store_true", help="빌드 결과물 초기화 후 빌드")
    args = parser.parse_args()

    print_build_info()

    # Determine target platform
    current_platform = platform.system()
    if args.mac:
        target_platform = "Darwin"
    elif args.win:
        target_platform = "Windows"
    else:
        target_platform = current_platform

    if args.clean:
        clean()
        print("[초기화] 이전 빌드 결과물 삭제 완료")
        print()

    # Step 1: PyInstaller build
    if not build_with_pyinstaller(target_platform):
        sys.exit(1)

    # Step 2: Platform-specific packaging
    if args.dmg and target_platform == "Darwin":
        create_dmg()
    elif target_platform == "Windows":
        create_windows_installer()
    elif target_platform == "Darwin":
        # Default: Just .app is fine, but suggest DMG
        print("[안내] DMG 생성을 원하면 --dmg 옵션을 추가하세요.")
        print(f"[결과] .app 번들: {os.path.join(DIST_DIR, APP_NAME + '.app')}")
    else:
        print(f"[결과] 실행 파일: {os.path.join(DIST_DIR, APP_NAME)}")

    print()
    print("=" * 60)
    print("  빌드 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
