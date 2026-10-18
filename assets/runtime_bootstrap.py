import atexit
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

try:
    IS_COLAB = importlib.util.find_spec('google.colab') is not None
except (ImportError, ModuleNotFoundError):
    IS_COLAB = False
SYSTEM_POSTGRES = IS_COLAB and sys.version_info >= (3, 13)
POSTGRES_BACKEND = 'system PostgreSQL 16' if SYSTEM_POSTGRES else 'pgserver 0.1.4'

def _version_tuple(value):
    return tuple(int(part) for part in re.findall(r'\d+', str(value).split()[0])[:3])

def setup_dependencies(required):
    if sys.version_info < (3, 9) or (sys.version_info >= (3, 13) and not SYSTEM_POSTGRES):
        raise RuntimeError('Use Python 3.9–3.12 locally or the standard Google Colab runtime.')
    modules = {'pgserver':'pgserver', 'psycopg2-binary':'psycopg2',
               'SQLAlchemy':'sqlalchemy', 'pandas':'pandas', 'numpy':'numpy',
               'matplotlib':'matplotlib', 'pyarrow':'pyarrow'}
    working = {}
    missing = []
    constraints = []
    for package, version in required.items():
        if package == 'pgserver' and SYSTEM_POSTGRES:
            continue
        module_name = modules[package]
        try:
            exists = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError):
            exists = False
        if not exists:
            missing.append(f'{package}=={version}')
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f'Installed {module_name} cannot be imported; reconnect to a clean runtime.') from exc
        actual = getattr(module, '__version__', None)
        if actual is None:
            actual = importlib.metadata.version(package)
        actual = str(actual).split()[0]
        numeric = _version_tuple(actual)
        compatible = {
            'pgserver': numeric == (0, 1, 4),
            'psycopg2-binary': (2, 9) <= numeric < (3,),
            'SQLAlchemy': (2, 0) <= numeric < (3,),
            'pandas': (2, 2) <= numeric < (3,),
            'numpy': ((2, 1) if sys.version_info >= (3, 13) else (1, 23)) <= numeric < (3,),
            'matplotlib': (3, 9) <= numeric < (4,),
            'pyarrow': (18,) <= numeric < (24,),
        }[package]
        if not compatible:
            raise RuntimeError(f'Unsupported installed {module_name} {actual}; use a clean Google Colab runtime.')
        working[module_name] = actual
        if package != 'psycopg2-binary':
            constraints.append(f'{package}=={actual}')
    for module_name in ['numpy', 'pandas', 'matplotlib', 'pyarrow']:
        module = sys.modules.get(module_name)
        actual = getattr(module, '__version__', None) if module is not None else None
        if actual is not None:
            constraints.append(f'{module_name}=={str(actual).split()[0]}')
    constraints = sorted(set(constraints))
    if missing:
        with tempfile.TemporaryDirectory(prefix='rdb-pip-') as directory:
            constraint = Path(directory) / 'constraints.txt'
            constraint.write_text('\n'.join(constraints)+'\n')
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                            '--index-url', 'https://pypi.org/simple',
                            '--constraint', str(constraint), '--only-binary=:all:', *missing], check=True)
    versions = {}
    for package in required:
        if package == 'pgserver' and SYSTEM_POSTGRES:
            continue
        module_name = modules[package]
        module = importlib.import_module(module_name)
        actual = getattr(module, '__version__', None)
        versions[module_name] = str(actual if actual is not None else importlib.metadata.version(package)).split()[0]
    print('Python:', sys.version.split()[0], '; packages:', versions)
    print('PostgreSQL backend:', POSTGRES_BACKEND)
    return versions

def _install_system_postgres16():
    binary = Path('/usr/lib/postgresql/16/bin')
    if all((binary/name).is_file() for name in ['postgres','initdb','pg_ctl']):
        return binary
    if not SYSTEM_POSTGRES or os.geteuid() != 0:
        raise RuntimeError('PostgreSQL 16 binaries are unavailable in this runtime.')
    apt_env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
    subprocess.run(['apt-get','update','-qq'], env=apt_env, check=True, timeout=180)
    subprocess.run(['apt-get','install','-y','-qq','--no-install-recommends','postgresql-common','ca-certificates'], env=apt_env, check=True, timeout=180)
    config = Path('/etc/postgresql-common/createcluster.conf')
    policy = Path('/usr/sbin/policy-rc.d')
    originals = {}
    for path in [config, policy]:
        if path.is_symlink():
            raise RuntimeError(f'Refusing to replace a system configuration symlink: {path}')
        originals[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
    try:
        old = config.read_text() if config.exists() else ''
        config.write_text(old+"\ncreate_main_cluster = false\n")
        policy.write_text('#!/bin/sh\nexit 101\n'); policy.chmod(0o755)
        subprocess.run(['apt-get','install','-y','-qq','--no-install-recommends','postgresql-16','postgresql-client-16'], env=apt_env, check=True, timeout=240)
    finally:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original[0]); path.chmod(original[1])
    if not all((binary/name).is_file() for name in ['postgres','initdb','pg_ctl']):
        raise RuntimeError('The runtime did not provide PostgreSQL 16 after APT installation.')
    return binary

class _SystemPostgres16:
    def __init__(self, data_dir, cleanup_mode='stop'):
        if cleanup_mode != 'stop':
            raise ValueError('Only cleanup_mode=stop is supported.')
        self.binary = _install_system_postgres16()
        requested = Path(data_dir)
        if requested.is_symlink() or requested.parent.is_symlink():
            raise RuntimeError('PostgreSQL data path must not be a symlink.')
        self.data = requested.resolve()
        self.parent = self.data.parent
        self.parent.mkdir(parents=True, exist_ok=True)
        self.marker = self.parent / '.rdb-pg16-owner.json'
        if self.marker.is_symlink():
            raise RuntimeError('The ownership marker must not be a symlink.')
        if self.data.exists() and not self.marker.is_file():
            raise RuntimeError('Existing PGDATA is not owned by this notebook runtime.')
        if self.marker.exists():
            owner = json.loads(self.marker.read_text())
            if owner.get('data_dir') != str(self.data):
                raise RuntimeError('The ownership marker does not match PGDATA.')
        self.marker.write_text(json.dumps({'data_dir':str(self.data),'backend':'system-postgresql-16'}))
        self.socket = Path(tempfile.mkdtemp(prefix='rdb-pg-socket-'))
        self.closed = False
        self.started = False
        import pwd
        account = pwd.getpwnam('postgres')
        for path in [self.parent, self.socket]:
            os.chown(path, account.pw_uid, account.pw_gid)
            path.chmod(0o700)
        self.prefix = ['runuser','-u','postgres','--'] if os.geteuid() == 0 else []
        try:
            if not (self.data/'PG_VERSION').exists():
                self._run('initdb','-D',str(self.data),'--username=postgres','--auth=trust','--encoding=UTF8','--locale=C.UTF-8')
            if (self.data/'PG_VERSION').read_text().strip() != '16':
                raise RuntimeError('The owned PGDATA is not PostgreSQL 16.')
            status = subprocess.run(self.prefix+[str(self.binary/'pg_ctl'),'-D',str(self.data),'status'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if status.returncode == 0:
                raise RuntimeError('The owned PostgreSQL server is already running; finish its cleanup before a new setup.')
            options = "-h '' -k "+shlex.quote(str(self.socket))+" -p 5432 -c unix_socket_permissions=0700"
            self.started = True
            self._run('pg_ctl','-D',str(self.data),'-l',str(self.parent/'postgres.log'),'-o',options,'-w','-t','60','start')
        except BaseException:
            self.cleanup()
            raise
        atexit.register(self.cleanup)
    def _run(self, name, *args):
        result = subprocess.run(self.prefix+[str(self.binary/name),*args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout)
        return result.stdout
    def get_uri(self):
        return 'postgresql://postgres@/postgres?host='+quote(str(self.socket),safe='')+'&port=5432'
    def cleanup(self):
        if self.closed:
            return
        if self.started and (self.data/'postmaster.pid').exists():
            self._run('pg_ctl','-D',str(self.data),'-m','fast','-w','-t','30','stop')
        if self.started and (self.data/'postmaster.pid').exists():
            raise RuntimeError('The owned PostgreSQL server has not stopped.')
        shutil.rmtree(self.socket, ignore_errors=True)
        self.closed = True

def get_local_server(data_dir, cleanup_mode='stop'):
    if SYSTEM_POSTGRES:
        return _SystemPostgres16(data_dir, cleanup_mode=cleanup_mode)
    import pgserver
    return pgserver.get_server(data_dir, cleanup_mode=cleanup_mode)
