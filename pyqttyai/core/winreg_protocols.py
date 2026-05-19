import winreg
import sys
import os

# You can combine both into a single .reg file to handle your network lab connections:
#
# Windows Registry Editor Version 5.00
#
# ; --- Telnet Handler ---
# [HKEY_CURRENT_USER\Software\Classes\telnet]
# @="URL:Telnet Protocol"
# "URL Protocol"=""
#
# [HKEY_CURRENT_USER\Software\Classes\telnet\shell\open\command]
# @="\"C:\\Path\\To\\pythonw.exe\" \"C:\\Path\\To\\Pyqttyai\\main.py\" \"%1\""
#
# ; --- SSH Handler ---
# [HKEY_CURRENT_USER\Software\Classes\ssh]
# @="URL:SSH Protocol"
# "URL Protocol"=""
#
# [HKEY_CURRENT_USER\Software\Classes\ssh\shell\open\command]
# @="\"C:\\Path\\To\\pythonw.exe\" \"C:\\Path\\To\\Pyqttyai\\main.py\" \"%1\""


def sync_protocol_registry(protocol):
    """Ensures the specific protocol points to the current executable."""
    # The path to this current running .exe
    executable_path = sys.executable

    # The command we want in the registry
    # Note: we use "%1" to pass the URL from the browser to the app
    if "python" in os.path.basename(executable_path).lower():
        # Use absolute path for the script location
        script_path = os.path.abspath(sys.argv[0])
        cmd_value = f'"{executable_path}" "{script_path}" "%1"'

    else:
        cmd_value = f'"{executable_path}" "%1"'

    # Root path: Software\Classes\telnet
    root_path = rf"Software\Classes\{protocol}"
    # Command path: Software\Classes\telnet\shell\open\command
    cmd_path = rf"{root_path}\shell\open\command"

    try:
        # 1. Setup the Root Protocol Key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_path) as root_key:
            # This is the @="URL:Protocol" part
            description = f"URL:{protocol.capitalize()} Protocol"
            winreg.SetValueEx(root_key, "", 0, winreg.REG_SZ, description)

            # This flag is what tells Windows it's a URI scheme
            winreg.SetValueEx(root_key, "URL Protocol", 0, winreg.REG_SZ, "")

        # 2. Setup the Command Key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
            try:
                current_val, _ = winreg.QueryValueEx(cmd_key, "")
            except FileNotFoundError:
                current_val = None

            # 3. Update only if the path has changed (e.g., moved exe)
            if current_val != cmd_value:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_value)
                print(f"Registry synced: {protocol} -> {cmd_value}")

    except Exception as e:
        print(f"Could not sync registry for {protocol}: {e}")
