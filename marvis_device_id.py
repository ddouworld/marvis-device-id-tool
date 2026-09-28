"""Marvis 1.60.2800.220 app-GUID manager. Windows/Python 3.10+, stdlib only.
Experimental v2: synchronize the Beacon GUID and two Marvis Env/svid values.
Local consistency is NOT proof of successful authentication or a stable session.
No Windows MachineGuid, QIMEI, credentials, EXE, DLL or validation branch is patched.
"""
from __future__ import annotations
import argparse, base64, ctypes as C, ctypes.wintypes as W, hashlib, json, os
from pathlib import Path
import re, subprocess, sys, tempfile, time, uuid, winreg
from datetime import datetime

TOOL_VERSION = '2.1.0-experimental'
VERSION = '1.60.2800.220'
ROOT = Path(r'D:\Program Files\Tencent\Marvis\Application')
INSTALL = ROOT / VERSION
CACHE = Path(os.environ.get('APPDATA', '')) / 'Tencent/beacon/beacon_marvis.db'
HOME = Path(__file__).resolve().parent
BACKUPS = HOME / 'backups'
EXPECTED_FILES = {
    'beacon_sdk.dll': '6ec162bd70b682e28c707bc0133df15efde644e2399a0ddee9b96cb4cc041c27',
    'Marvis.exe': 'e821aa87dca7aeb138ab7691e61365a80b14ee33f64abb796f46ec1bf2af80d1',
    'MarvisSvr.exe': '7f4b9f5224d8858462b6883bdd0b0a3191c8f05bf3f2f7d33e92753b55772902',
    'base.dll': '7d2a5b52ee952c55573e0b2b69134174c3b2ec17741a8a9828c40e4cb4665900',
}
EXPORT = '?BeaconDeviceId@BeaconClient@@SAAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@XZ'
DESCRIPTION = 'BeaconGuidData'
STOPPED_SERVICE = False
SAFE_TO_RESTART = True

class AuditError(RuntimeError): pass
class Blob(C.Structure):
    _fields_ = [('cbData', W.DWORD), ('pbData', C.POINTER(C.c_ubyte))]

def digest(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def masked(guid: str) -> str: return guid[:4] + '...' + guid[-4:]
def validate_guid(value: str) -> str:
    if not re.fullmatch(r'[0-9a-fA-F]{32}', value):
        raise AuditError('GUID must be exactly 32 hexadecimal characters, without hyphens.')
    if int(value, 16) == 0: raise AuditError('All-zero GUID is not accepted.')
    return value.lower()

class TransactionLock:
    def __init__(self):
        self.k=C.WinDLL('kernel32',use_last_error=True)
        self.k.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];self.k.CreateMutexW.restype=W.HANDLE
        self.k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];self.k.WaitForSingleObject.restype=W.DWORD
        self.k.ReleaseMutex.argtypes=[W.HANDLE];self.k.ReleaseMutex.restype=W.BOOL
        self.k.CloseHandle.argtypes=[W.HANDLE];self.k.CloseHandle.restype=W.BOOL
        name='Global\\MarvisGuidManagerV2-'+digest(str(INSTALL).lower().encode())[:20]
        self.handle=self.k.CreateMutexW(None,False,name)
        if not self.handle:raise C.WinError(C.get_last_error())
        if self.k.WaitForSingleObject(self.handle,0) not in (0,0x80):
            self.k.CloseHandle(self.handle);self.handle=None
            raise AuditError('Another GUID transaction is active; try again after it finishes.')
    def close(self):
        if self.handle:
            self.k.ReleaseMutex(self.handle);self.k.CloseHandle(self.handle);self.handle=None

def require_windows():
    if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
        raise AuditError('Use 64-bit Python on Windows.')

def validate_install():
    require_windows()
    for name, expected in EXPECTED_FILES.items():
        p = INSTALL / name
        if not p.is_file() or digest(p.read_bytes()) != expected:
            raise AuditError(f'Unsupported or changed binary: {p}. No files were changed.')
    if CACHE.name != 'beacon_marvis.db' or CACHE.is_symlink() or CACHE.resolve()!=CACHE.absolute():
        raise AuditError('Unexpected cache target or symlink.')
    if not CACHE.is_file(): raise AuditError(f'Cache not found: {CACHE}')

class DPAPI:
    def __init__(self):
        require_windows()
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.c = C.WinDLL('crypt32', use_last_error=True)
        self.k.LocalFree.argtypes = [C.c_void_p]; self.k.LocalFree.restype = C.c_void_p
        self.k.GetPrivateProfileStringW.argtypes = [W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,W.LPWSTR,W.DWORD,W.LPCWSTR]
        self.k.GetPrivateProfileStringW.restype = W.DWORD
        self.k.WritePrivateProfileStringW.argtypes = [W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,W.LPCWSTR]
        self.k.WritePrivateProfileStringW.restype = W.BOOL
        self.c.CryptUnprotectData.argtypes = [C.POINTER(Blob), C.POINTER(W.LPWSTR), C.c_void_p, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Blob)]
        self.c.CryptUnprotectData.restype = W.BOOL
        self.c.CryptProtectData.argtypes = [C.POINTER(Blob), W.LPCWSTR, C.c_void_p, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Blob)]
        self.c.CryptProtectData.restype = W.BOOL
    def transform(self, data: bytes, protect: bool, description: str = DESCRIPTION):
        backing = (C.c_ubyte * len(data)).from_buffer_copy(data)
        src = Blob(len(data), backing); dst = Blob(); desc = W.LPWSTR()
        # UI_FORBIDDEN; no optional entropy, no LOCAL_MACHINE flag.
        if protect:
            ok = self.c.CryptProtectData(C.byref(src), description, None, None, None, 1, C.byref(dst))
        else:
            ok = self.c.CryptUnprotectData(C.byref(src), C.byref(desc), None, None, None, 1, C.byref(dst))
        if not ok: raise C.WinError(C.get_last_error())
        try:
            result = C.string_at(dst.pbData, dst.cbData)
            return result, description if protect else desc.value
        finally:
            if dst.pbData: self.k.LocalFree(dst.pbData)
            if desc: self.k.LocalFree(C.cast(desc, C.c_void_p))
    def get(self, path: Path, key: str):
        buf = C.create_unicode_buffer(8192)
        n = self.k.GetPrivateProfileStringW('QMGuid', key, '', buf, len(buf), str(path.resolve()))
        if n >= len(buf)-1: raise AuditError('Truncated INI field.')
        return buf.value
    def set(self, path: Path, key: str, value: str):
        if not self.k.WritePrivateProfileStringW('QMGuid', key, value, str(path.resolve())):
            raise C.WinError(C.get_last_error())
    def read(self, path: Path):
        if self.get(path, 'encrypted') != '1': raise AuditError('Expected encrypted=1.')
        try: encrypted = base64.b64decode(self.get(path, 'guid'), validate=True)
        except ValueError as e: raise AuditError('Invalid Base64 record.') from e
        plain, description = self.transform(encrypted, False)
        if description != DESCRIPTION: raise AuditError('Unexpected DPAPI description.')
        parse_record(plain)
        return plain
    def set_plain(self, path: Path, plain: bytes):
        parse_record(plain)
        encrypted, _ = self.transform(plain, True)
        check, desc = self.transform(encrypted, False)
        if check != plain or desc != DESCRIPTION: raise AuditError('DPAPI round-trip failed.')
        self.set(path, 'guid', base64.b64encode(encrypted).decode('ascii'))
        if self.read(path) != plain: raise AuditError('INI round-trip failed.')

def parse_record(plain: bytes) -> dict[bytes, bytes]:
    fields = {}
    for part in plain.split(b'&'):
        key, sep, value = part.partition(b'=')
        if not sep or key in fields: raise AuditError('Unexpected/duplicate record field.')
        fields[key] = value
    if set(fields) != {b'guid',b'mac',b'hdd',b'cpu',b'hashway'} or fields[b'hashway'] != b'1':
        raise AuditError('Unsupported Beacon record schema.')
    for key in (b'guid',b'mac',b'hdd',b'cpu'):
        if not re.fullmatch(rb'[0-9a-fA-F]{32}', fields[key]):
            raise AuditError('Unexpected identifier format; refusing to guess.')
    return fields

def replace_guid(plain: bytes, guid: str) -> bytes:
    guid = validate_guid(guid); before = parse_record(plain)
    result = b'&'.join(b'guid='+guid.encode() if part.startswith(b'guid=') else part for part in plain.split(b'&'))
    after = parse_record(result)
    if len(result) != len(plain) or any(after[k] != v for k,v in before.items() if k != b'guid'):
        raise AuditError('Non-GUID record fields changed.')
    return result

def write_bytes_atomic(path: Path, content: bytes):
    fd, tmpname = tempfile.mkstemp(prefix=path.name+'.marvis-id-', suffix='.tmp', dir=path.parent)
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()

def build_candidate(api: DPAPI, original: bytes, desired: bytes, directory: Path) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='candidate-',suffix='.ini',dir=directory)
    os.close(fd); path = Path(name)
    try:
        path.write_bytes(original); api.set_plain(path, desired)
        return path.read_bytes()
    finally: path.unlink(missing_ok=True)

def powershell(script: str, *, timeout: int = 30):
    env = dict(os.environ, MARVIS_ID_INSTALL=str(INSTALL), MARVIS_ID_PRODUCT_ROOT=str(ROOT.parent))
    p = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)
    if p.returncode: raise AuditError(f'Process command failed (exit {p.returncode}): '+(p.stderr+p.stdout).strip()[:400])
    return p.stdout.strip()

def processes():
    text = powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $root=$env:MARVIS_ID_PRODUCT_ROOT+'\\'; @((Get-CimInstance Win32_Process) | Where-Object {$_.ExecutablePath -and $_.ExecutablePath.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)} | Select-Object Name,ProcessId,ExecutablePath) | ConvertTo-Json -Compress")
    data = json.loads(text or '[]')
    return [data] if isinstance(data,dict) else data or []

def ensure_stopped(stop_background: bool):
    global STOPPED_SERVICE
    found = processes()
    background_names = {'marvissvr.exe', 'crashpad_handler.exe'}
    foreground = [x for x in found if x['Name'].lower() not in background_names or Path(x['ExecutablePath']).parent != INSTALL]
    if foreground: raise AuditError('Close Marvis and its foreground components first. Running: '+', '.join(x['Name'] for x in foreground))
    if found and not stop_background: raise AuditError('MarvisSvr is running. Close it or pass --stop-background.')
    if any(x['Name'].lower() == 'marvissvr.exe' for x in found):
        service_text=powershell("Get-CimInstance Win32_Service -Filter \"Name='MarvisSvr'\" | Select-Object State,ProcessId,PathName | ConvertTo-Json -Compress")
        service=json.loads(service_text or '{}')
        if service.get('State')!='Running' or int(service.get('ProcessId',0)) not in {int(x['ProcessId']) for x in found if x['Name'].lower()=='marvissvr.exe'} or Path(service.get('PathName','').strip(chr(34))) != INSTALL/'MarvisSvr.exe':
            raise AuditError('MarvisSvr is not the expected running SCM service; refusing automatic shutdown.')
        STOPPED_SERVICE = True  # The original running SCM service was verified.
        script = "$s=Get-CimInstance Win32_Service -Filter \"Name='MarvisSvr'\"; if($s -and $s.State -eq 'Running'){if($s.PathName.Trim([char]34) -ne ($env:MARVIS_ID_INSTALL+'\\MarvisSvr.exe')){throw 'Service path mismatch'}; Stop-Service -Name 'MarvisSvr' -Confirm:$false -ErrorAction Stop; (Get-Service 'MarvisSvr').WaitForStatus('Stopped',[TimeSpan]::FromSeconds(15)); 'SERVICE_STOPPED'}"
        if 'SERVICE_STOPPED' in powershell(script): STOPPED_SERVICE = True
    for proc in sorted(found, key=lambda x: x['Name'].lower() != 'marvissvr.exe'):
        pid = int(proc['ProcessId'])
        filename = proc['Name']
        if filename.lower() not in background_names: raise AuditError('Unexpected background process.')
        script = f"$p=Get-Process -Id {pid} -ErrorAction SilentlyContinue; if($p){{if($p.Path -ne ($env:MARVIS_ID_INSTALL+'\\{filename}')){{throw 'Process path changed'}}; Stop-Process -Id {pid} -Force -Confirm:$false -ErrorAction Stop; $p.WaitForExit(8000) | Out-Null}}; exit 0"
        powershell(script)
    if processes(): raise AuditError('Marvis restarted during shutdown; no modification performed.')

def restart_background():
    global STOPPED_SERVICE
    if not SAFE_TO_RESTART: raise AuditError('Rollback is incomplete; background restart was intentionally withheld.')
    if not STOPPED_SERVICE: return False
    powershell("$s=Get-CimInstance Win32_Service -Filter \"Name='MarvisSvr'\"; if(!$s -or $s.PathName.Trim([char]34) -ne ($env:MARVIS_ID_INSTALL+'\\MarvisSvr.exe')){throw 'Service path mismatch'}; Start-Service -Name 'MarvisSvr' -ErrorAction Stop; (Get-Service 'MarvisSvr').WaitForStatus('Running',[TimeSpan]::FromSeconds(15))")
    STOPPED_SERVICE=False
    return True

def native_child(expected: str | None):
    validate_install()
    # Normal SDK identity read, in a disposable subprocess; no login/HTTP API calls.
    dll_search_handle = os.add_dll_directory(str(INSTALL))
    dll = C.WinDLL(str(INSTALL/'beacon_sdk.dll'), winmode=0x1100)
    func = getattr(dll, EXPORT); func.argtypes=[]; func.restype=C.c_void_p
    address = func()
    if not address: raise AuditError('Native SDK returned null.')
    layout = C.string_at(address,32)
    size = int.from_bytes(layout[16:24],'little'); capacity=int.from_bytes(layout[24:32],'little')
    if size != 32 or capacity < size or capacity > 1048576: raise AuditError('Unexpected native string ABI.')
    data = C.string_at(int.from_bytes(layout[:8],'little'),size)
    if not re.fullmatch(rb'[0-9a-f]{32}',data): raise AuditError('Invalid native GUID result.')
    h=digest(data)
    result={'native_guid_sha256':h,'native_guid_masked':masked(data.decode()),'matches_expected':expected is None or h==expected}
    if expected and h != expected: raise AuditError('Native SDK did not adopt the requested GUID.')
    return result

def probe(expected: str):
    p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'_native-probe','--expected',expected],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode: raise AuditError('Native verification failed: '+(p.stdout+p.stderr).strip()[-500:])
    for line in reversed(p.stdout.splitlines()):
        try:
            value=json.loads(line)
            if isinstance(value,dict) and 'native_guid_sha256' in value: return value
        except json.JSONDecodeError: pass
    raise AuditError('No native verification result.')

# Deliberately fixed scope. No arbitrary registry paths, no MachineGuid or Androws writes.
REG_PATH = r'SOFTWARE\Tencent\Marvis\Env'
REG_NAME = 'svid'
REG_HIVES = ('HKLM', 'HKCU')
REG_DESCRIPTION = 'MarvisGuidManager-registry-v2'
MANIFEST_SCHEMA = 2

class Registry:
    def _open(self, hive, write=False):
        if hive not in REG_HIVES: raise AuditError('Unexpected registry hive.')
        root = {'HKLM':winreg.HKEY_LOCAL_MACHINE,'HKCU':winreg.HKEY_CURRENT_USER}[hive]
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY
        if write: access |= winreg.KEY_SET_VALUE
        return winreg.OpenKey(root, REG_PATH, 0, access)
    def snapshot(self):
        result={}
        for hive in REG_HIVES:
            try:
                with self._open(hive) as key: value, kind=winreg.QueryValueEx(key,REG_NAME)
            except FileNotFoundError as e:
                raise AuditError(f'{hive} Marvis Env/svid is absent; no keys will be created.') from e
            if kind!=winreg.REG_SZ or not isinstance(value,str): raise AuditError('svid is not REG_SZ.')
            validate_guid(value)
            result[hive]={'type':kind,'value':value}
        return result
    def preflight(self):
        self.snapshot()
        for hive in REG_HIVES:
            try:
                with self._open(hive,True): pass
            except PermissionError as e:
                raise AuditError('Administrator rights under the SAME Windows user are required to update Marvis svid.') from e
    def write_one(self,hive,entry):
        validate_registry_snapshot({h:entry for h in REG_HIVES})
        with self._open(hive,True) as key:
            winreg.SetValueEx(key,REG_NAME,0,entry['type'],entry['value'])
            winreg.FlushKey(key)
            actual,kind=winreg.QueryValueEx(key,REG_NAME)
        if actual!=entry['value'] or kind!=entry['type']: raise AuditError(f'{hive} svid read-back mismatch.')

def validate_registry_snapshot(snapshot):
    if not isinstance(snapshot,dict) or set(snapshot)!=set(REG_HIVES): raise AuditError('Unexpected registry backup structure.')
    for entry in snapshot.values():
        if set(entry)!={'type','value'} or entry['type']!=winreg.REG_SZ: raise AuditError('Unexpected registry backup type.')
        validate_guid(entry['value'])

def guid_hash(value): return digest(value.lower().encode('ascii'))
def registry_summary(snapshot):
    return {h:{'path':h+'\\'+REG_PATH,'name':REG_NAME,'view':'64-bit','type':'REG_SZ',
               'guid_masked':masked(v['value']),'guid_sha256':guid_hash(v['value'])} for h,v in snapshot.items()}
def same_guid(snapshot,guid): return all(v['value'].lower()==guid.lower() for v in snapshot.values())
def target_registry(snapshot,guid):
    return {h:{'type':entry['type'],'value':validate_guid(guid)} for h,entry in snapshot.items()}
def save_json(path,data): write_bytes_atomic(path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))
def read_state(api,reg):
    data=CACHE.read_bytes();plain=api.read(CACHE)
    return data,plain,reg.snapshot()

def verify_local(api,reg,desired_plain,desired_registry):
    if api.read(CACHE)!=desired_plain: raise AuditError('Beacon payload differs from the intended record.')
    if reg.snapshot()!=desired_registry: raise AuditError('Registry svid differs from the intended state.')
    guid=parse_record(desired_plain)[b'guid'].decode('ascii')
    if not same_guid(desired_registry,guid): raise AuditError('Beacon/HKLM/HKCU identity mismatch.')
    return guid_hash(guid)

def recover_state(api,reg,original_bytes,original_registry,allowed_plains,allowed_registries):
    """Compensating recovery; never overwrite an unrelated concurrent identity."""
    problems=[]
    for hive in reversed(REG_HIVES):
        try:
            current=reg.snapshot()
            if current[hive] not in [state[hive] for state in allowed_registries]:
                problems.append(hive+': unexpected concurrent value; not overwritten')
            elif current[hive]!=original_registry[hive]:reg.write_one(hive,original_registry[hive])
        except Exception as e:problems.append(hive+': '+type(e).__name__)
    try:
        if CACHE.read_bytes()!=original_bytes:
            if api.read(CACHE) not in allowed_plains:problems.append('Unexpected concurrent Beacon record; not overwritten')
            else:write_bytes_atomic(CACHE,original_bytes)
    except Exception as e:problems.append('Beacon: '+type(e).__name__)
    try:
        if CACHE.read_bytes()!=original_bytes:problems.append('Beacon checksum mismatch')
        if reg.snapshot()!=original_registry:problems.append('Registry recovery mismatch')
    except Exception as e:problems.append('Recovery read-back: '+type(e).__name__)
    return problems

def legacy_or_v2_backup(api,backup_id=None):
    if backup_id is None:
        choices=sorted(BACKUPS.glob('*/manifest.json'))
        # Skip completed restores. Prefer the newest active or uncertain transaction.
        selected=[]
        for p in choices:
            try:meta=json.loads(p.read_text(encoding='utf-8'))
            except Exception:raise AuditError('Unreadable backup manifest; select a known backup explicitly.')
            if meta.get('status') not in {'restored','rolled_back'}:selected.append(p)
        if not selected:raise AuditError('No active backup; select an explicit --backup-id if needed.')
        path=selected[-1]
    else:
        if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',backup_id):raise AuditError('Invalid backup id.')
        path=BACKUPS/backup_id/'manifest.json'
    if path.is_symlink() or not path.resolve().is_relative_to(BACKUPS.resolve()):raise AuditError('Backup path escapes the backup directory.')
    item=json.loads(path.read_text(encoding='utf-8'))
    if item.get('cache_path')!=str(CACHE) or item.get('version')!=VERSION:raise AuditError('Backup machine/path/version mismatch.')
    raw=(path.parent/'original.dpapi.ini').read_bytes()
    if digest(raw)!=item['before_file_sha256']:raise AuditError('Original cache backup checksum mismatch.')
    before_plain=api.read(path.parent/'original.dpapi.ini')
    if guid_hash(parse_record(before_plain)[b'guid'].decode())!=item['before_guid_sha256']:
        raise AuditError('Backup GUID checksum mismatch.')
    if item.get('schema',1)==MANIFEST_SCHEMA:
        rb=(path.parent/'registry.before.dpapi').read_bytes()
        if digest(rb)!=item['registry_backup_sha256']:raise AuditError('Registry backup checksum mismatch.')
        decoded,description=api.transform(rb,False)
        if description!=REG_DESCRIPTION:raise AuditError('Wrong registry DPAPI backup description.')
        registry=json.loads(decoded.decode('utf-8'));validate_registry_snapshot(registry)
        if not same_guid(registry,parse_record(before_plain)[b'guid'].decode()):raise AuditError('Backup baseline is inconsistent.')
    elif item.get('schema',1)==1:
        registry=None  # A v1 backup never captured registry data; do not fabricate it.
    else:raise AuditError('Unsupported backup version.')
    return path,item,raw,before_plain,registry

def change(args):
    global SAFE_TO_RESTART
    validate_install();api=DPAPI();reg=Registry();reg.preflight()
    initial_bytes,initial_plain,initial_reg=read_state(api,reg)
    old=parse_record(initial_plain)[b'guid'].decode();new=validate_guid(args.new_id or uuid.uuid4().hex)
    if not same_guid(initial_reg,old):
        raise AuditError('Baseline GUID/svid mismatch. Restore the prior v1 backup first; v2 will not guess the original identity.')
    if new==old.lower():return {'status':'unchanged','tool_version':TOOL_VERSION,'guid_masked':masked(new),'login_stability_verified':False}
    ensure_stopped(args.stop_background)
    before,plain,snapshot=read_state(api,reg)
    if (before,plain,snapshot)!=(initial_bytes,initial_plain,initial_reg):raise AuditError('State changed while stopping components; retry after a clean exit.')
    backup_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    folder=BACKUPS/backup_id;folder.mkdir(parents=True)
    write_bytes_atomic(folder/'original.dpapi.ini',before)
    registry_cipher,_=api.transform(json.dumps(snapshot,sort_keys=True).encode('utf-8'),True,REG_DESCRIPTION)
    write_bytes_atomic(folder/'registry.before.dpapi',registry_cipher)
    desired=replace_guid(plain,new);new_registry=target_registry(snapshot,new)
    candidate=build_candidate(api,before,desired,folder)
    item={'schema':MANIFEST_SCHEMA,'tool_version':TOOL_VERSION,'backup_id':backup_id,'version':VERSION,
        'cache_path':str(CACHE),'created_local':datetime.now().astimezone().isoformat(),
        'before_file_sha256':digest(before),'registry_backup_sha256':digest(registry_cipher),
        'before_guid_sha256':guid_hash(old),'after_guid_sha256':guid_hash(new),'after_guid_masked':masked(new),
        'status':'prepared','stage':'backups_verified','registry_targets':registry_summary(snapshot),
        'registry_changed':True,'windows_machine_guid_changed':False,'login_stability_verified':False}
    manifest=folder/'manifest.json';save_json(manifest,item)
    # Verify both backups before mutating either resource.
    legacy_or_v2_backup(api,backup_id)
    if processes() or read_state(api,reg)!=(before,plain,snapshot):raise AuditError('Concurrent application/state change; no write performed.')
    touched=False
    try:
        item['stage']='write_registry';save_json(manifest,item)
        for hive in REG_HIVES:
            if processes():raise AuditError('A Marvis component started during the transaction.')
            now=reg.snapshot()
            if now[hive]!=snapshot[hive]:raise AuditError('Registry changed concurrently.')
            touched=True;reg.write_one(hive,new_registry[hive])
            item['stage']='registry_written_'+hive;save_json(manifest,item)
        if CACHE.read_bytes()!=before or processes():raise AuditError('Cache changed or Marvis restarted before cache commit.')
        item['stage']='write_cache';save_json(manifest,item)
        touched=True;write_bytes_atomic(CACHE,candidate)
        verify_local(api,reg,desired,new_registry)
        checks=[]
        for _ in range(2):
            if processes():raise AuditError('Marvis started before verification completed.')
            checks.append(probe(item['after_guid_sha256']))
            verify_local(api,reg,desired,new_registry)
        validate_install()
        item.update(status='applied',stage='local_checks_passed',native_probes=checks,after_file_sha256=digest(CACHE.read_bytes()),
                    local_identity_consistent=True,non_guid_fields_preserved=True)
        save_json(manifest,item)
    except (Exception, KeyboardInterrupt) as e:
        problems=recover_state(api,reg,before,snapshot,[plain,desired],[snapshot,new_registry]) if touched else []
        if problems:SAFE_TO_RESTART=False
        item.update(status='rollback_failed' if problems else 'rolled_back',stage='recovery',
                    failure=type(e).__name__,recovery_problems=problems)
        try:save_json(manifest,item)
        except Exception:pass
        raise AuditError(('Recovery incomplete; retain backup '+backup_id+'. ' if problems else 'Original cache and svid restored. ')+str(e)) from e
    return {'status':'applied','tool_version':TOOL_VERSION,'backup_id':backup_id,'guid_masked':masked(new),
        'native_fresh_process_checks':2,'local_identity_consistent':True,'svid_hklm_synced':True,'svid_hkcu_synced':True,
        'registry_changed':True,'non_guid_fields_preserved':True,'windows_machine_guid_changed':False,
        'binaries_changed':False,'qimei_change_claimed':False,'login_stability_verified':False,
        'next_step':'Sign in manually and verify subsequent checkLogin results; applied only means local checks passed.'}

def restore(args):
    global SAFE_TO_RESTART
    validate_install();api=DPAPI();reg=Registry()
    path,item,original,before_plain,before_reg=legacy_or_v2_backup(api,args.backup_id)
    legacy_backup=before_reg is None
    reg.preflight();initial=read_state(api,reg)
    current_bytes,current_plain,current_reg=initial;old_guid=parse_record(before_plain)[b'guid'].decode()
    old_fields=parse_record(before_plain);current_fields=parse_record(current_plain)
    if any(current_fields[k]!=v for k,v in old_fields.items() if k!=b'guid'):
        raise AuditError('Non-GUID hardware fields changed since backup; refusing to replace unrelated data.')
    if before_reg is None:
        # Legacy backups are safe only when the registry already matches the original GUID.
        if not same_guid(current_reg,old_guid):raise AuditError('v1 backup has no registry snapshot; refusing to alter svid. Use the corresponding v2 backup.')
        before_reg=current_reg
    allowed={item['before_guid_sha256'],item['after_guid_sha256']}
    if guid_hash(parse_record(current_plain)[b'guid'].decode()) not in allowed:
        raise AuditError('Current Beacon GUID belongs to a different transaction.')
    for h in REG_HIVES:
        if guid_hash(current_reg[h]['value']) not in {guid_hash(before_reg[h]['value']),item['after_guid_sha256']}:
            raise AuditError('Current svid belongs to a different transaction; refusing overwrite.')
    if current_bytes==original and current_reg==before_reg:
        return {'status':'already_restored','backup_id':item['backup_id'],'local_identity_consistent':True,'login_stability_verified':False}
    ensure_stopped(args.stop_background)
    if processes() or read_state(api,reg)!=initial:raise AuditError('State changed during restore preflight.')
    touched=False
    try:
        item.update(restore_stage='write_registry');save_json(path,item)
        for h in REG_HIVES:
            if processes():raise AuditError('Marvis started during restore.')
            if reg.snapshot()[h]!=before_reg[h]:touched=True;reg.write_one(h,before_reg[h])
        if processes():raise AuditError('Marvis started before file restore.')
        touched=True;write_bytes_atomic(CACHE,original)
        verify_local(api,reg,before_plain,before_reg)
        probe(item['before_guid_sha256'])
        verify_local(api,reg,before_plain,before_reg)
        item.update(status='restored',restore_stage='verified',restored_local=datetime.now().astimezone().isoformat())
        save_json(path,item)
    except (Exception, KeyboardInterrupt) as e:
        problems=recover_state(api,reg,current_bytes,current_reg,[current_plain,before_plain],[current_reg,before_reg]) if touched else []
        if problems:SAFE_TO_RESTART=False
        item.update(restore_stage='rollback_failed' if problems else 'restore_rolled_back',restore_failure=type(e).__name__,recovery_problems=problems)
        try:save_json(path,item)
        except Exception:pass
        raise AuditError('Restore failed; '+('recovery incomplete.' if problems else 'pre-restore state reinstated.')) from e
    return {'status':'restored','tool_version':TOOL_VERSION,'backup_id':item['backup_id'],
        'original_file_restored':CACHE.read_bytes()==original,'registry_snapshot_restored':not legacy_backup and reg.snapshot()==before_reg,
        'registry_restore_mode':'v1_file_only_registry_checked' if legacy_backup else 'v2_snapshot_restored',
        'local_identity_consistent':True,'login_stability_verified':False}

def status(args):
    validate_install();api=DPAPI();reg=Registry();_,plain,snapshot=read_state(api,reg)
    guid=parse_record(plain)[b'guid'].decode()
    result={'status':'read_only','tool_version':TOOL_VERSION,'version':VERSION,'cache_path':str(CACHE),
        'guid_masked':masked(guid),'guid_sha256':guid_hash(guid),'svid':registry_summary(snapshot),
        'local_identity_consistent':same_guid(snapshot,guid),'encrypted':True,'login_stability_verified':False,
        'running_processes':[{'name':x['Name'],'pid':x['ProcessId']} for x in processes()],
        'backup_ids':[x.parent.name for x in sorted(BACKUPS.glob('*/manifest.json'))]}
    if args.reveal:result['guid']=guid
    return result

def check_login(args):
    """Parse only event names/numeric codes locally. Never emit full log lines or tokens."""
    validate_install();path=INSTALL/'logs/MarvisSvr.log'
    if not path.exists():raise AuditError('Service log not found.')
    since=datetime.fromisoformat(args.since) if args.since else datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
    if since.tzinfo:since=since.astimezone().replace(tzinfo=None)
    events=[]
    for number,line in enumerate(path.read_text(encoding='utf-8',errors='replace').splitlines(),1):
        if not re.match(r'\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}',line):continue
        try:stamp=datetime.strptime(str(since.year)+'-'+line[:18],'%Y-%m-%d %H:%M:%S.%f')
        except ValueError:continue
        if stamp<since:continue
        kind=None;code=None
        if 'CLoginService::OnFetchCheckLogin' in line:
            match=re.search(r'fetch check login, code:\s*(-?\d+)',line)
            if match:kind='checkLogin_result';code=int(match[1])
            elif '[Msg]: logout' in line:kind='checkLogin_logout'
        if 'CLoginBackend::FetchCheckLogin' in line:
            match=re.search(r'marvis_check_login reply error:\s*(-?\d+)',line)
            if match:kind='server_checkLogin_error';code=int(match[1])
        if 'CLoginService::BrocastUserinfoEvent' in line:
            normalized=line.replace('\\"','"')
            match=re.search(r'"eventName"\s*:\s*"(login|logout)"',normalized)
            if match:kind=match[1]
        if kind:events.append({'time_local':stamp.isoformat(timespec='milliseconds'),'line':number,'kind':kind,'code':code})
    last_login=max((i for i,x in enumerate(events) if x['kind']=='login'),default=-1)
    relevant=events[last_login:] if last_login>=0 else events
    checks=sum(x['kind']=='checkLogin_result' and x['code']==0 for x in relevant)
    failed=any(x['kind'] in {'logout','checkLogin_logout','server_checkLogin_error'} or (x['kind']=='checkLogin_result' and x['code']!=0) for x in relevant)
    return {'status':'read_only','since_local':since.isoformat(),'events':events[-40:],
        'login_event_observed':last_login>=0,'successful_checks_after_latest_login':checks,
        'failure_after_latest_login':failed,'login_stability_verified':False,
        'interpretation':'Observed login failure; consider restoring this transaction.' if failed else 'Only historical observations; continue manual session testing, not a stability guarantee.'}

CLOSE_PROCESS_NAMES = (
    'MarvisKnowledgebase.exe', 'MarvisDlSvr.exe', 'MarvisAgent.exe',
    'MarvisHost.exe', 'MarvisMCP.exe', 'Marvis.exe',
)

def close_script():
    """Constant allowlist, verified executable paths; no taskkill /T or wildcard kills."""
    names=','.join("'"+name+"'" for name in CLOSE_PROCESS_NAMES)
    return r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
$allowed=@(__ALLOWED__)
$root=[IO.Path]::GetFullPath($env:MARVIS_ID_PRODUCT_ROOT).TrimEnd('\')+'\'
function Get-Targets {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and ($allowed -contains $_.Name) -and
        ([IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($root,[StringComparison]::OrdinalIgnoreCase))
    })
}
$found=@(Get-Targets)
$entries=[Collections.Generic.List[object]]::new()
$errors=[Collections.Generic.List[object]]::new()
foreach($item in $found) {
    try {
        $p=Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
        if(!$p){continue}
        $path=[IO.Path]::GetFullPath($p.Path)
        if(!$path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase) -or
           $path -ne [IO.Path]::GetFullPath($item.ExecutablePath) -or
           $allowed -notcontains ($p.ProcessName+'.exe')) {throw 'Process path/name changed; skipped'}
        $handle=$p.Handle
        $entries.Add([pscustomobject]@{Process=$p;Name=$item.Name;Id=$p.Id;Forced=$false})
    } catch {
        $errors.Add([pscustomobject]@{name=$item.Name;pid=$item.ProcessId;message=$_.Exception.Message})
    }
}
try {
    # Ask all windowed targets to exit first, then give them a shared grace period.
    foreach($entry in $entries) {
        try {if(!$entry.Process.HasExited){$null=$entry.Process.CloseMainWindow()}} catch {}
    }
    $deadline=[DateTime]::UtcNow.AddSeconds(5)
    foreach($entry in $entries) {
        try {
            $left=[int][Math]::Max(0,($deadline-[DateTime]::UtcNow).TotalMilliseconds)
            if(!$entry.Process.HasExited -and $left -gt 0){$null=$entry.Process.WaitForExit($left)}
        } catch {}
    }
    foreach($entry in $entries) {
        try {
            if(!$entry.Process.HasExited) {
                $live=$entry.Process
                $path=[IO.Path]::GetFullPath($live.Path)
                if(!$path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase) -or
                   $allowed -notcontains ($live.ProcessName+'.exe')) {throw 'Process target changed; skipped'}
                Stop-Process -InputObject $live -Force -Confirm:$false -ErrorAction Stop
                $entry.Forced=$true
            }
        } catch {
            $errors.Add([pscustomobject]@{name=$entry.Name;pid=$entry.Id;message=$_.Exception.Message})
        }
    }
    $deadline=[DateTime]::UtcNow.AddSeconds(5)
    foreach($entry in $entries) {
        try {
            $left=[int][Math]::Max(0,($deadline-[DateTime]::UtcNow).TotalMilliseconds)
            if(!$entry.Process.HasExited -and $left -gt 0){$null=$entry.Process.WaitForExit($left)}
        } catch {}
    }
    $remaining=@(Get-Targets | ForEach-Object {[pscustomobject]@{name=$_.Name;pid=$_.ProcessId}})
    $closed=@($entries | Where-Object {$_.Process.HasExited} | ForEach-Object {
        [pscustomobject]@{name=$_.Name;pid=$_.Id;forced=$_.Forced}
    })
    $state=if($remaining.Count -or $errors.Count){'partial'}elseif(!$found.Count){'already_closed'}else{'closed'}
    [pscustomobject]@{status=$state;matched=$found.Count;closed=$closed;remaining=$remaining;errors=@($errors.ToArray());service_untouched=$true;guid_and_registry_untouched=$true} | ConvertTo-Json -Depth 6 -Compress
} finally {
    foreach($entry in $entries){$entry.Process.Dispose()}
}
'''.replace('__ALLOWED__',names)

def close_marvis(args):
    require_windows()
    if not getattr(args,'yes',False):
        answer=input('将关闭指定的六种 Marvis 进程，必要时强制结束，未保存内容可能丢失。请先保存；确认请输入 YES：').strip()
        if answer!='YES':return {'status':'cancelled','action':'close-marvis'}
    result=json.loads(powershell(close_script(),timeout=45))
    if not isinstance(result,dict) or result.get('status') not in {'closed','partial','already_closed'}:
        raise AuditError('Unexpected process-close result.')
    result['tool_version']=TOOL_VERSION
    result['target_process_names']=list(CLOSE_PROCESS_NAMES)
    return result

def run_action(command,args):
    """One lock/restart/error lifecycle per action, not per menu session."""
    global SAFE_TO_RESTART
    lock=None;result=None
    changes_identity=command in {'change','restore'}
    try:
        if command in {'change','close-marvis'} and not SAFE_TO_RESTART:
            raise AuditError('A previous rollback was incomplete; inspect status and restore the matching backup first.')
        if command in {'change','restore','close-marvis'}:lock=TransactionLock()
        funcs={'status':status,'change':change,'restore':restore,'check-login':check_login,'close-marvis':close_marvis}
        result=native_child(args.expected) if command=='_native-probe' else funcs[command](args)
        if command=='restore' and result.get('status') in {'restored','already_restored'} and result.get('local_identity_consistent'):
            SAFE_TO_RESTART=True
        result['background_service_restarted']=restart_background() if changes_identity else False
        return result,0
    except (Exception,KeyboardInterrupt) as e:
        recovery=None
        if changes_identity:
            try:restart_background()
            except Exception as restart_error:recovery=str(restart_error)
        error={'status':'cancelled' if isinstance(e,KeyboardInterrupt) else 'error',
               'tool_version':TOOL_VERSION,'message':'Operation interrupted.' if isinstance(e,KeyboardInterrupt) else str(e),
               'background_restart_error':recovery}
        if result and result.get('status') in {'applied','restored'}:
            error.update(status='background_restart_failed',local_operation=result,local_changes_completed=True)
        return error,1
    finally:
        if lock:lock.close()

def menu_selection(choice):
    if choice in {'1','5'}:return 'status',argparse.Namespace(reveal=choice=='5')
    if choice=='6':return 'close-marvis',argparse.Namespace(yes=False)
    if choice=='7':return 'check-login',argparse.Namespace(since=None)
    if choice=='4':return 'restore',argparse.Namespace(backup_id=None,stop_background=True)
    if choice not in {'2','3'}:raise AuditError('Invalid menu selection. Choose 0–7.')
    if input('将修改应用 GUID 和两处 svid；确认请输入 YES：').strip()!='YES':return None,None
    value=validate_guid(input('输入 32 位十六进制 GUID：').strip()) if choice=='3' else None
    return 'change',argparse.Namespace(new_id=value,stop_background=True)

def menu():
    while True:
        print(f'\nMarvis GUID + svid 同步工具 v2.1（实验版，仅支持 {VERSION}）')
        print('每项执行后返回此菜单；只有选 0 才正常退出脚本。')
        print('1. 只读查看 GUID/svid 一致性\n2. 生成新 GUID 并同步 svid\n3. 自定义 GUID 并同步 svid\n4. 恢复最近一次事务（含 svid）\n5. 查看完整 GUID\n6. 关闭 Marvis（指定六种进程）\n7. 只读检查今天的登录日志\n0. 退出脚本')
        try:
            choice=input('选择：').strip()
            if choice=='0':print('已退出脚本。');return 0
            command,args=menu_selection(choice)
            result,_=run_action(command,args) if command else ({'status':'cancelled'},0)
            print(json.dumps(result,ensure_ascii=False))
        except EOFError:
            # A closed terminal/stdin cannot accept another menu selection; avoid a busy loop.
            print('输入已关闭，结束脚本。');return 1
        except KeyboardInterrupt:
            print('\n当前输入已取消；返回主菜单，选择 0 退出。')
        except Exception as e:
            print(json.dumps({'status':'error','tool_version':TOOL_VERSION,'message':str(e)},ensure_ascii=False))

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('menu');s=sub.add_parser('status');s.add_argument('--reveal',action='store_true')
    c=sub.add_parser('change');c.add_argument('--new-id');c.add_argument('--stop-background',action='store_true')
    r=sub.add_parser('restore');r.add_argument('--backup-id');r.add_argument('--stop-background',action='store_true')
    l=sub.add_parser('check-login');l.add_argument('--since',help='Local ISO timestamp, e.g. 2026-09-08T16:00:00')
    x=sub.add_parser('close-marvis');x.add_argument('--yes',action='store_true',help='Skip the save-work confirmation for closing the six named Marvis processes.')
    n=sub.add_parser('_native-probe',help=argparse.SUPPRESS);n.add_argument('--expected')
    args=parser.parse_args()
    if args.command=='menu':return menu()
    result,code=run_action(args.command,args)
    print(json.dumps(result,ensure_ascii=False));return code
if __name__=='__main__':raise SystemExit(main())
