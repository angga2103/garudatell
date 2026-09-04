import os
import shutil

os.makedirs('archive/legacy_scripts', exist_ok=True)
os.makedirs('archive/app_backups', exist_ok=True)

KEEP_ROOT_FILES = {
    '.env', 'ai_handover_rules.md', 'changelog.md', 'version', 
    'requirements.txt', 'run.py', 'wsgi.py', 'start_production.sh', 
    'garudatel.service', 'wa_bot_config.json', 'otp_database.json', 
    '.gitignore', 'readme.md'
}

# 1. Pindahkan legacy scripts dari root
moved_root = 0
for f in os.listdir('.'):
    if os.path.isfile(f) and f.lower() not in KEEP_ROOT_FILES:
        shutil.move(f, os.path.join('archive/legacy_scripts', f))
        moved_root += 1

print(f'Successfully moved {moved_root} legacy files from root to archive/legacy_scripts/')

# 2. Pindahkan folder backup_ui_master & scans jika ada
if os.path.exists('backup_ui_master'):
    shutil.move('backup_ui_master', 'archive/ui_master_backups')
    print('Moved backup_ui_master to archive/ui_master_backups')

if os.path.exists('scans'):
    shutil.move('scans', 'archive/scans')
    print('Moved scans to archive/scans')

# 3. Pindahkan folder app/templates_bak_20260802_113530 jika ada
if os.path.exists('app/templates_bak_20260802_113530'):
    shutil.move('app/templates_bak_20260802_113530', 'archive/app_backups/templates_bak_20260802_113530')
    print('Moved app/templates_bak_20260802_113530 to archive/app_backups/')

# 4. Pindahkan file broken / backup di dalam folder app/
moved_app = 0
for root, dirs, files in os.walk('app'):
    for f in files:
        fl = f.lower()
        if any(fl.endswith(ext) for ext in ['.bak', '.broken', '.broken_2', '.broken_backup']) or 'bak015' in fl or 'bak_' in fl or 'auth_backup' in fl:
            src = os.path.join(root, f)
            dest = os.path.join('archive/app_backups', f)
            if os.path.exists(dest):
                prefix = root.replace('\\', '_').replace('/', '_')
                dest = os.path.join('archive/app_backups', f'{prefix}_{f}')
            shutil.move(src, dest)
            moved_app += 1

print(f'Successfully moved {moved_app} backup files from app/ to archive/app_backups/')

