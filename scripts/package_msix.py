"""Package the Windows build (build/stickle.dist) as an MSIX, for the Microsoft Store.

    uv run python scripts/package_msix.py --publisher "CN=..." --arch x64 [--sign]

The Store signs the package it publishes. --sign signs it with a test
certificate made for the purpose, only so it can be installed to try it out
(the certificate must then be trusted on that computer; see the .cer written
next to the package).

Notes are written to the real %APPDATA%\\Stickle, as the other Windows builds
do: MSIX would otherwise keep what the app writes there in a folder of the
package's own and delete it when the app is removed, notes and all. Starting
at login is a StartupTask of the package, off until the user turns it on.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "build" / "stickle.dist"
OUT = ROOT / "build" / "msix"
APP_ID = "co.linkro.stickle"
STARTUP_TASK = "StickleStartup"
LOGOS = {"Square44x44Logo.png": 44, "Square150x150Logo.png": 150, "StoreLogo.png": 50}

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:desktop6="http://schemas.microsoft.com/appx/manifest/desktop/windows10/6"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap desktop desktop6 rescap">
  <Identity Name="{app_id}" Publisher="{publisher}" Version="{version}"
    ProcessorArchitecture="{arch}"/>
  <Properties>
    <DisplayName>Stickle</DisplayName>
    <PublisherDisplayName>{publisher_name}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <desktop6:FileSystemWriteVirtualization>disabled</desktop6:FileSystemWriteVirtualization>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0"
      MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Resources>
    <Resource Language="en-us"/>
    <Resource Language="ko-kr"/>
  </Resources>
  <Applications>
    <Application Id="Stickle" Executable="stickle.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="Stickle" Description="Sticky notes that follow you"
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png"/>
      <Extensions>
        <desktop:Extension Category="windows.startupTask" Executable="stickle.exe"
          EntryPoint="Windows.FullTrustApplication">
          <desktop:StartupTask TaskId="{startup_task}" Enabled="false" DisplayName="Stickle"/>
        </desktop:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust"/>
    <rescap:Capability Name="unvirtualizedResources"/>
  </Capabilities>
</Package>
"""


def package_version() -> str:
    """The Store wants four numbers: 0.2.0 becomes 0.2.0.0."""
    sys.path.insert(0, str(ROOT / "src"))
    from stickle import __version__

    numbers = [int(part) for part in __version__.split(".")[:3]]
    return ".".join(str(n) for n in [*numbers, 0])


def write_logos(folder: Path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    from stickle.app.tray import make_icon

    app = QGuiApplication.instance() or QGuiApplication(["package_msix", "-platform", "offscreen"])
    folder.mkdir(parents=True, exist_ok=True)
    for name, size in LOGOS.items():
        pixmap = make_icon().pixmap(size, size)
        pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio).save(str(folder / name))
    del app


def windows_sdk_tool(name: str) -> str:
    """makeappx.exe or signtool.exe from the newest Windows SDK installed."""
    found = shutil.which(name)
    if found:
        return found
    kits = Path("C:/Program Files (x86)/Windows Kits/10/bin")
    # x64 tools also run on ARM (emulated); an ARM-only SDK has its own.
    candidates = sorted(kits.glob(f"10.*/x64/{name}")) or sorted(kits.glob(f"10.*/arm64/{name}"))
    if not candidates:
        raise SystemExit(f"{name} not found: install the Windows SDK")
    return str(candidates[-1])


def sign(package: Path, publisher: str) -> None:
    """With a test certificate for publisher, and the certificate saved next to it."""
    pfx = package.with_suffix(".pfx")
    cer = package.with_suffix(".cer")
    script = (
        f"$cert = New-SelfSignedCertificate -Type Custom -Subject '{publisher}'"
        " -KeyUsage DigitalSignature -FriendlyName 'Stickle test'"
        " -CertStoreLocation Cert:\\CurrentUser\\My"
        " -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}');"
        " $password = ConvertTo-SecureString -String 'stickle-test' -Force -AsPlainText;"
        f" Export-PfxCertificate -Cert $cert -FilePath '{pfx}' -Password $password | Out-Null;"
        f" Export-Certificate -Cert $cert -FilePath '{cer}' | Out-Null;"
        # Kept only in the files: nothing is left in this computer's certificate store.
        " Remove-Item -Path ('Cert:\\CurrentUser\\My\\' + $cert.Thumbprint)"
    )
    # Started from PowerShell 7 (as in CI), Windows PowerShell would inherit its
    # module path and not find its own certificate module (the Cert: drive).
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, env=env)
    signtool = windows_sdk_tool("signtool.exe")
    subprocess.run(
        [signtool, "sign", "/fd", "SHA256", "/f", str(pfx), "/p", "stickle-test", str(package)],
        check=True,
    )
    pfx.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publisher", required=True, help='as the Store gives it: "CN=..."')
    parser.add_argument("--publisher-name", default="Linkro")
    parser.add_argument("--arch", choices=["x64", "arm64"], default="x64")
    parser.add_argument("--sign", action="store_true", help="sign with a test certificate")
    options = parser.parse_args()
    if not (DIST / "stickle.exe").exists():
        raise SystemExit(f"{DIST} has no stickle.exe: run scripts/build.py first")

    layout = OUT / "layout"
    shutil.rmtree(layout, ignore_errors=True)
    shutil.copytree(DIST, layout)
    write_logos(layout / "Assets")
    manifest = MANIFEST.format(
        app_id=APP_ID,
        publisher=escape(options.publisher, {'"': "&quot;"}),
        publisher_name=escape(options.publisher_name),
        version=package_version(),
        arch=options.arch,
        startup_task=STARTUP_TASK,
    )
    (layout / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    package = OUT / f"stickle-windows-{options.arch}.msix"
    package.unlink(missing_ok=True)
    makeappx = windows_sdk_tool("makeappx.exe")
    subprocess.run([makeappx, "pack", "/o", "/d", str(layout), "/p", str(package)], check=True)
    if options.sign:
        sign(package, options.publisher)
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
