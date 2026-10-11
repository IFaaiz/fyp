"""Read-only Outlook installation preflight. Never opens a profile/mailbox."""
import importlib.util
import os


def outlook_preflight() -> dict:
    result = {"platform": os.name, "pywin32_available": importlib.util.find_spec("win32com") is not None,
              "classic_com_registered": False, "office_version": None, "office_products": None,
              "mailbox_read": False, "live_integration_verified": False}
    if os.name != "nt":
        return result
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID", 0, winreg.KEY_READ | view) as key:
                result["classic_com_registered"] = bool(winreg.QueryValueEx(key, "")[0])
        except OSError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration", 0, winreg.KEY_READ | view) as key:
                result["office_version"] = winreg.QueryValueEx(key, "VersionToReport")[0]
                result["office_products"] = winreg.QueryValueEx(key, "ProductReleaseIds")[0]
        except OSError:
            pass
    result["status"] = "READY_FOR_AUTHORIZED_PROFILE_TEST" if result["classic_com_registered"] and result["pywin32_available"] else "PREREQUISITE_MISSING"
    return result
