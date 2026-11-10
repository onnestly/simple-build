import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path.cwd()
CACHE = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.cache'))) / 'simple-build' / 'cache'
OUTPUT = ROOT / 'output'
USER_AGENT = 'UniversalModBuilder/1.0'


def request_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as response, target.open('wb') as out:
        shutil.copyfileobj(response, out)


def ask_choice(title, choices):
    print('\n' + title)
    for i, value in enumerate(choices, 1):
        print(f'  {i}. {value}')
    while True:
        answer = input('> ').strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer)-1]
        print('Enter a number from the list.')


def version_key(v):
    return tuple(int(n) for n in v.split('.'))


def java_major(mc):
    v = version_key(mc)
    if v >= (1, 20, 5):
        return 21
    if v >= (1, 18):
        return 17
    if v >= (1, 17):
        return 16
    return 8


def java_version(java):
    try:
        result = subprocess.run([str(java), '-version'], capture_output=True, text=True, timeout=15)
        m = re.search(r'version "(\d+)(?:\.(\d+))?', result.stderr + result.stdout)
        if m:
            return int(m.group(2)) if m.group(1) == '1' else int(m.group(1))
        m = re.search(r'openjdk (\d+)', result.stderr + result.stdout)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def find_java(major):
    exe = 'java.exe' if os.name == 'nt' else 'java'
    for path in [CACHE / 'jdk' / str(major) / 'bin' / exe, Path(os.environ.get('JAVA_HOME', '')) / 'bin' / exe]:
        if path.is_file() and java_version(path) == major:
            return path
    which = shutil.which('java')
    if which and java_version(which) == major:
        return Path(which)
    return None


def safe_extract_zip(archive, dest):
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            p = (dest / member.filename).resolve()
            if not p.is_relative_to(dest.resolve()):
                raise ValueError('Unsafe archive path')
        z.extractall(dest)


def safe_extract_tar(archive, dest):
    with tarfile.open(archive, 'r:gz') as t:
        for member in t.getmembers():
            p = (dest / member.name).resolve()
            if not p.is_relative_to(dest.resolve()) or member.issym() or member.islnk():
                raise ValueError('Unsafe archive path')
        t.extractall(dest)


def install_java(major):
    cached = find_java(major)
    if cached:
        print(f'Java {major}: {cached}')
        return cached
    print(f'Downloading Java {major} (Temurin)...')
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'mac'}.get(platform.system())
    machine = platform.machine().lower()
    arch = 'aarch64' if machine in ('arm64', 'aarch64') else 'x64' if machine in ('amd64', 'x86_64') else None
    if not system or not arch:
        raise RuntimeError('Unsupported OS/CPU architecture for automatic Java installation')
    url = f'https://api.adoptium.net/v3/assets/latest/{major}/hotspot?architecture={arch}&image_type=jdk&os={system}&vendor=eclipse'
    assets = request_json(url)
    if not assets:
        raise RuntimeError('Temurin API did not return a matching JDK')
    pkg = assets[0]['binary']['package']
    suffix = '.zip' if system == 'windows' else '.tar.gz'
    archive = CACHE / 'downloads' / f'temurin-{major}{suffix}'
    if not archive.is_file():
        download(pkg['link'], archive)
    stage = CACHE / 'jdk' / f'.stage-{major}'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        if suffix == '.zip':
            safe_extract_zip(archive, stage)
        else:
            safe_extract_tar(archive, stage)
        exe = 'java.exe' if system == 'windows' else 'java'
        matches = list(stage.rglob('bin/' + exe))
        if not matches:
            raise RuntimeError('JDK archive does not contain java')
        home = matches[0].parent.parent
        final = CACHE / 'jdk' / str(major)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(home), str(final))
        return final / 'bin' / exe
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def project_info():
    files = [ROOT / 'gradle.properties', ROOT / 'build.gradle', ROOT / 'build.gradle.kts', ROOT / 'settings.gradle', ROOT / 'settings.gradle.kts']
    return '\n'.join(f.read_text(encoding='utf-8-sig', errors='replace') for f in files if f.exists())


def detect_loader(text):
    if re.search(r'net\.fabricmc\.fabric-loom|fabric-loom|fabricmc', text, re.I):
        return 'Fabric'
    if re.search(r'net\.neoforged|neoforge', text, re.I):
        return 'NeoForge'
    if re.search(r'net\.minecraftforge\.gradle|net\.minecraftforge:forge|forgegradle', text, re.I):
        return 'Forge'
    return None


def detect_mc(text):
    for pattern in [r'(?m)^\s*(?:minecraft_version|mc_version)\s*=\s*["\']?(1\.\d+(?:\.\d+)?)',
                    r'net\.minecraftforge:forge:(1\.\d+(?:\.\d+)?)-',
                    r'net\.minecraft:minecraft:(1\.\d+(?:\.\d+)?)',
                    r'(?m)^\s*minecraft_version\s*=\s*(1\.\d+(?:\.\d+)?)']:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return None


def gradle_version():
    props = ROOT / 'gradle' / 'wrapper' / 'gradle-wrapper.properties'
    if props.exists():
        m = re.search(r'gradle-([\d.]+)-(?:bin|all)\.zip', props.read_text(errors='replace'))
        if m:
            return m.group(1)
    return None


def install_gradle(version):
    folder = CACHE / 'gradle' / ('gradle-' + version)
    exe = folder / 'bin' / ('gradle.bat' if os.name == 'nt' else 'gradle')
    if exe.exists():
        return exe
    print(f'Downloading Gradle {version}...')
    archive = CACHE / 'downloads' / f'gradle-{version}-bin.zip'
    if not archive.exists():
        download(f'https://services.gradle.org/distributions/gradle-{version}-bin.zip', archive)
    dest = CACHE / 'gradle'
    dest.mkdir(parents=True, exist_ok=True)
    try:
        safe_extract_zip(archive, dest)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    if os.name != 'nt':
        exe.chmod(exe.stat().st_mode | 0o111)
    return exe


def build(loader, mc):
    if not (ROOT / 'build.gradle').exists() and not (ROOT / 'build.gradle.kts').exists():
        raise RuntimeError('No build.gradle or build.gradle.kts found. Put the builder in an existing mod project root.')
    info = project_info()
    detected_loader = detect_loader(info)
    detected_mc = detect_mc(info)
    if detected_loader and detected_loader != loader:
        raise RuntimeError(f'Project is configured for {detected_loader}, not {loader}. Switching loaders requires porting source code.')
    if not detected_loader:
        raise RuntimeError('Could not detect Fabric/Forge from Gradle configuration. Refusing an unverified build.')
    if detected_mc and detected_mc != mc:
        raise RuntimeError(f'Project targets Minecraft {detected_mc}, not {mc}. Change the project configuration and mappings first.')
    if not detected_mc:
        print('WARNING: Could not verify Minecraft version from build files. Selected version is not injected into Gradle.')
    major = java_major(mc)
    java = install_java(major)
    gradle_wrapper = ROOT / 'gradle' / 'wrapper' / 'gradle-wrapper.jar'
    wrapper_script = ROOT / ('gradlew.bat' if os.name == 'nt' else 'gradlew')
    if gradle_wrapper.exists() and wrapper_script.exists():
        command = ['cmd', '/c', str(wrapper_script)] if os.name == 'nt' else ['sh', str(wrapper_script)]
    else:
        version = gradle_version()
        if not version:
            raise RuntimeError('No complete Gradle wrapper. Add gradlew, gradle/wrapper/gradle-wrapper.jar and gradle-wrapper.properties.')
        command = [str(install_gradle(version))]
    env = os.environ.copy()
    env['GRADLE_USER_HOME'] = str(CACHE / 'gradle-user-home')
    env['JAVA_HOME'] = str(java.parent.parent)
    env['PATH'] = str(java.parent) + os.pathsep + env.get('PATH', '')
    print(f'Building {loader} {mc} with Java {major}...')
    log = ROOT / 'umb-build.log'
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command + ['--no-daemon', 'build'], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        for line in process.stdout:
            print(line, end='')
            stream.write(line)
        code = process.wait()
    if code:
        raise RuntimeError(f'Gradle build failed (exit code {code}). See umb-build.log')
    libs = ROOT / 'build' / 'libs'
    jars = [p for p in libs.glob('*.jar') if not any(x in p.name for x in ('-sources', '-dev', '-javadoc', '-shadow'))]
    if not jars:
        raise RuntimeError('Gradle succeeded, but no distributable JAR was found in build/libs')
    OUTPUT.mkdir(exist_ok=True)
    for jar in jars:
        shutil.copy2(jar, OUTPUT / jar.name)
        print('READY:', OUTPUT / jar.name)


def cache_size(folder):
    total = 0
    if folder.exists():
        for base, _, names in os.walk(folder):
            for name in names:
                try:
                    total += (Path(base) / name).stat().st_size
                except OSError:
                    pass
    return total


def human_size(size):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.2f} {unit}'
        value /= 1024


def show_cache():
    print(f'{human_size(cache_size(CACHE))} ({CACHE})')
    print('For clear: simple-build clear')


def clear_cache():
    print(f'Cache: {CACHE}')
    print(f'Size: {human_size(cache_size(CACHE))}')
    if not CACHE.exists():
        print('Cache is already empty.')
        return
    answer = input('Delete all Simple Build cached files? [y/N]: ').strip().lower()
    if answer not in ('y', 'yes'):
        print('Cancelled.')
        return
    shutil.rmtree(CACHE)
    print('Cache cleared.')


def main():
    print('=== Simple Build 1.2 ===')
    command = sys.argv[1].lower() if len(sys.argv) == 2 else ''
    if command == 'cache':
        show_cache()
        return
    if command == 'clear':
        clear_cache()
        return
    if command != 'start':
        print('Usage: simple-build start | cache | clear')
        return
    loader = ask_choice('Select mod loader:', ['Forge', 'Fabric'])
    versions = ['1.16.5', '1.17.1', '1.18.2', '1.19.2', '1.19.4', '1.20.1', '1.20.4', '1.20.6', '1.21.1', '1.21.4']
    mc = ask_choice('Select Minecraft version:', versions)
    print('\nProject directory:', ROOT)
    build(loader, mc)
    print('\nBUILD SUCCESSFUL')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print('\nBUILD FAILED:', exc)
        sys.exit(1)
